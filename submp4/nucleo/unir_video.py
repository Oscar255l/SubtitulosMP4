"""Unir subtítulos a un video MP4 usando FFmpeg (fase 3, RF-10 a RF-13).

Cómo funciona:
    1. Cada subtítulo se pasa por la misma limpieza de la conversión y se
       guarda como SRT en UTF-8 en una carpeta temporal. Así cualquier
       formato o codificación funciona, y no hay líneas superpuestas
       (el MP4 no las soporta).
    2. FFmpeg copia el video y el audio tal cual (sin recodificar, por eso
       tarda segundos) y agrega cada SRT como pista "mov_text", que es el
       formato de subtítulos que entiende el MP4.
    3. El resultado se guarda en un archivo NUEVO: el original no se toca.

SEGURIDAD (RNF-03): FFmpeg se ejecuta con las protecciones del módulo
ffmpeg.py (lista de argumentos sin shell, rutas con "file:" y "-n").
"""

import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from submp4.nucleo.bilingue import combinar_bilingue
from submp4.nucleo.conversion import ErrorConversion, guardar_srt, leer_lineas
from submp4.nucleo.ffmpeg import (
    ErrorFFmpeg,
    buscar_ffmpeg,
    como_archivo,
    duracion_video,
    ejecutar_ffmpeg,
)
from submp4.nucleo.idiomas import nombre_de_idioma
from submp4.nucleo.rutas import ruta_sin_conflicto


class ErrorUnion(Exception):
    """Error con un mensaje pensado para mostrárselo al usuario."""


@dataclass(frozen=True)
class PistaSubtitulo:
    """Un subtítulo que se va a agregar al video."""

    ruta: Path
    idioma: str = "eng"  # Código ISO 639-2, ej. "eng", "spa"
    nombre: str = ""  # Nombre visible de la pista; si está vacío se usa el idioma


@dataclass(frozen=True)
class ResultadoUnion:
    """Resumen de la unión, para mostrarlo en la ventana."""

    ruta_salida: Path
    pistas_agregadas: int


def ruta_salida_disponible(ruta_video: Path) -> Path:
    """Calcula dónde guardar el video con subtítulos sin pisar nada (RF-12).

    "Pelicula.mp4" -> "Pelicula.subs.mp4"
    Si ya existe   -> "Pelicula.subs (2).mp4", "Pelicula.subs (3).mp4"…
    """
    ruta_video = Path(ruta_video)
    return ruta_sin_conflicto(
        ruta_video.with_name(f"{ruta_video.stem}.subs{ruta_video.suffix}")
    )


# ---------------------------------------------------------------------------
# 1. Armar el comando (función pura: fácil de probar)
# ---------------------------------------------------------------------------


def construir_comando(
    ffmpeg: str,
    ruta_video: Path,
    subtitulos: list[tuple[Path, str, str]],
    ruta_salida: Path,
    por_defecto: int | None = 0,
    conservar_existentes: bool = True,
) -> list[str]:
    """Arma la lista de argumentos para FFmpeg.

    subtitulos: lista de (ruta_srt_utf8, idioma, nombre_visible).
    por_defecto: índice de la pista que queda activa al abrir el video, o None.
    conservar_existentes: mantener los subtítulos que el video ya traía.

    Las pistas nuevas se ponen PRIMERO, así la pista k nueva es siempre la
    pista de subtítulos k del archivo de salida.
    """
    comando = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-n"]
    comando += ["-i", como_archivo(ruta_video)]
    for ruta_srt, _, _ in subtitulos:
        comando += ["-i", como_archivo(ruta_srt)]

    # Qué pistas van a la salida: video, audio, subtítulos nuevos y existentes.
    # El "?" significa "si existe", para que no falle si el video no tiene audio.
    comando += ["-map", "0:v?", "-map", "0:a?"]
    for numero in range(1, len(subtitulos) + 1):
        comando += ["-map", f"{numero}:0"]
    if conservar_existentes:
        comando += ["-map", "0:s?"]

    # Copiar video y audio sin recodificar; los subtítulos van como mov_text.
    comando += ["-c", "copy", "-c:s", "mov_text"]

    for indice, (_, idioma, nombre) in enumerate(subtitulos):
        comando += [f"-metadata:s:s:{indice}", f"language={idioma}"]
        comando += [f"-metadata:s:s:{indice}", f"handler_name={nombre}"]

    # Ninguna pista activa por defecto… excepto la elegida.
    comando += ["-disposition:s", "0"]
    if por_defecto is not None:
        comando += [f"-disposition:s:{por_defecto}", "default"]

    # Progreso en formato clave=valor por la salida estándar.
    comando += ["-progress", "pipe:1", "-nostats"]
    comando.append(como_archivo(ruta_salida))
    return comando


# ---------------------------------------------------------------------------
# 2. Función principal
# ---------------------------------------------------------------------------


def _validar(
    ruta_video: Path, pistas: list[PistaSubtitulo], por_defecto: int | None, bilingue: bool
) -> None:
    if not ruta_video.is_file():
        raise ErrorUnion(f"No existe el video: {ruta_video}")
    if ruta_video.suffix.lower() != ".mp4":
        raise ErrorUnion("El video debe ser un archivo .mp4")
    if not pistas:
        raise ErrorUnion("Elige al menos un subtítulo.")
    for pista in pistas:
        if not re.fullmatch(r"[a-z]{3}", pista.idioma):
            raise ErrorUnion(f"Código de idioma no válido: {pista.idioma!r}")
    if bilingue and len(pistas) != 2:
        raise ErrorUnion("Para la pista bilingüe se necesitan exactamente dos subtítulos.")
    total_pistas = len(pistas) + (1 if bilingue else 0)
    if por_defecto is not None and not 0 <= por_defecto < total_pistas:
        raise ErrorUnion("La pista por defecto no existe.")


def unir_subtitulos(
    ruta_video: Path,
    pistas: list[PistaSubtitulo],
    por_defecto: int | None = 0,
    conservar_existentes: bool = True,
    al_progresar: Callable[[float], None] | None = None,
    ruta_salida: Path | None = None,
    incluir_bilingue: bool = False,
) -> ResultadoUnion:
    """Une una o varias pistas de subtítulos al MP4, sin recodificar (RF-10, RF-11).

    al_progresar: función que recibe el avance (0 a 1) mientras FFmpeg trabaja.
    incluir_bilingue: con dos pistas, agrega una tercera con la primera arriba
        y la segunda en cursiva debajo (fase 4). Las pistas quedan en orden:
        pista 1, pista 2, bilingüe; por_defecto=2 deja activa la bilingüe.
    """
    ruta_video = Path(ruta_video)
    _validar(ruta_video, pistas, por_defecto, incluir_bilingue)

    ffmpeg = buscar_ffmpeg()
    if not ffmpeg:
        raise ErrorUnion("FFmpeg no está instalado. Revisa el README para instalarlo.")

    salida = Path(ruta_salida) if ruta_salida else ruta_salida_disponible(ruta_video)
    if salida.resolve() == ruta_video.resolve():
        raise ErrorUnion("La salida no puede ser el mismo video original.")

    with tempfile.TemporaryDirectory(prefix="submp4_") as carpeta:
        carpeta = Path(carpeta)

        # Paso 1: cada subtítulo a SRT limpio en UTF-8.
        preparados = []
        lecturas = []
        for indice, pista in enumerate(pistas):
            try:
                lectura = leer_lineas(pista.ruta)
            except ErrorConversion as error:
                raise ErrorUnion(f"Subtítulo «{Path(pista.ruta).name}»: {error}") from None
            if not lectura.lineas:
                raise ErrorUnion(f"El subtítulo «{Path(pista.ruta).name}» no tiene diálogos.")
            lecturas.append(lectura)
            temporal = carpeta / f"pista_{indice}.srt"
            guardar_srt(lectura.lineas, temporal, pista.ruta)
            nombre = pista.nombre or nombre_de_idioma(pista.idioma)
            preparados.append((temporal, pista.idioma, nombre))

        # Paso 1b (opcional): pista bilingüe, primera arriba y segunda en cursiva.
        if incluir_bilingue:
            temporal = carpeta / "pista_bilingue.srt"
            guardar_srt(
                combinar_bilingue(lecturas[0].lineas, lecturas[1].lineas),
                temporal,
                pistas[0].ruta,
            )
            nombre = f"{preparados[0][2]} + {preparados[1][2]}"  # Ej. "Inglés + Español"
            preparados.append((temporal, pistas[0].idioma, nombre))

        # Paso 2: llamar a FFmpeg.
        comando = construir_comando(
            ffmpeg, ruta_video, preparados, salida, por_defecto, conservar_existentes
        )
        try:
            ejecutar_ffmpeg(comando, salida, duracion_video(ruta_video), al_progresar)
        except ErrorFFmpeg as error:
            consejo = (
                "\nSi el video ya traía subtítulos de imagen, prueba desmarcando "
                "«Conservar los subtítulos que ya trae el video»."
                if conservar_existentes
                else ""
            )
            raise ErrorUnion(
                f"FFmpeg no pudo unir los subtítulos:\n{error.detalle}{consejo}"
            ) from None

    return ResultadoUnion(ruta_salida=salida, pistas_agregadas=len(preparados))
