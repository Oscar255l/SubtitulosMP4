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

SEGURIDAD (RNF-03):
    - FFmpeg se ejecuta con subprocess pasando una LISTA de argumentos y sin
      shell=True: un nombre de archivo como 'pelicula"; del *.mp4' nunca se
      interpreta como un comando.
    - Las rutas se pasan absolutas y con el prefijo "file:", para que FFmpeg
      no confunda un archivo llamado "-y.mp4" con una opción, ni uno llamado
      "http:algo" con una dirección de internet.
    - Se usa "-n": FFmpeg nunca sobrescribe un archivo existente.
"""

import re
import shutil
import subprocess  # nosec B404 - se usa de forma segura (ver arriba)
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from submp4.nucleo.bilingue import combinar_bilingue
from submp4.nucleo.conversion import ErrorConversion, guardar_srt, leer_lineas
from submp4.nucleo.rutas import ruta_sin_conflicto

# Nombre visible -> código de idioma ISO 639-2 que guarda el MP4.
IDIOMAS = {
    "Inglés": "eng",
    "Español": "spa",
    "Portugués": "por",
    "Francés": "fre",
    "Italiano": "ita",
    "Alemán": "ger",
    "Japonés": "jpn",
    "Sin especificar": "und",
}

# En Windows, evita que se abra una ventana negra de consola al llamar a FFmpeg.
_SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


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


def buscar_ffmpeg() -> str | None:
    """Devuelve la ruta de FFmpeg si está instalado, o None si no (RF-16)."""
    return shutil.which("ffmpeg")


def ruta_salida_disponible(ruta_video: Path) -> Path:
    """Calcula dónde guardar el video con subtítulos sin pisar nada (RF-12).

    "Pelicula.mp4" -> "Pelicula.subs.mp4"
    Si ya existe   -> "Pelicula.subs (2).mp4", "Pelicula.subs (3).mp4"…
    """
    ruta_video = Path(ruta_video)
    return ruta_sin_conflicto(
        ruta_video.with_name(f"{ruta_video.stem}.subs{ruta_video.suffix}")
    )


def _nombre_de_idioma(codigo: str) -> str:
    for nombre, valor in IDIOMAS.items():
        if valor == codigo:
            return nombre
    return codigo


def _como_archivo(ruta: Path) -> str:
    """Ruta absoluta con prefijo "file:" (ver SEGURIDAD arriba)."""
    return f"file:{Path(ruta).resolve()}"


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
    comando += ["-i", _como_archivo(ruta_video)]
    for ruta_srt, _, _ in subtitulos:
        comando += ["-i", _como_archivo(ruta_srt)]

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
    comando.append(_como_archivo(ruta_salida))
    return comando


# ---------------------------------------------------------------------------
# 2. Progreso (RF-13)
# ---------------------------------------------------------------------------


def duracion_video(ruta_video: Path) -> float | None:
    """Duración del video en segundos usando ffprobe, o None si no se puede."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        salida = subprocess.run(  # nosec B603 - lista de argumentos, sin shell
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", _como_archivo(ruta_video)],
            capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
            creationflags=_SIN_VENTANA,
        )
        return float(salida.stdout.strip())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


_TIEMPO_PROCESADO = re.compile(r"^out_time_(?:us|ms)=(\d+)$")


def fraccion_de_progreso(linea: str, duracion: float | None) -> float | None:
    """Lee una línea de "-progress" y devuelve el avance entre 0 y 1.

    Devuelve None si la línea no dice nada del avance.
    """
    linea = linea.strip()
    if linea == "progress=end":
        return 1.0
    coincidencia = _TIEMPO_PROCESADO.match(linea)
    if not coincidencia or not duracion:
        return None
    segundos = int(coincidencia.group(1)) / 1_000_000  # Viene en microsegundos
    return max(0.0, min(1.0, segundos / duracion))


# ---------------------------------------------------------------------------
# 3. Función principal
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
            nombre = pista.nombre or _nombre_de_idioma(pista.idioma)
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
        duracion = duracion_video(ruta_video)
        registro_errores = carpeta / "errores.txt"

        with registro_errores.open("w", encoding="utf-8") as errores:
            proceso = subprocess.Popen(  # nosec B603 - lista de argumentos, sin shell
                comando,
                stdout=subprocess.PIPE,
                stderr=errores,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=_SIN_VENTANA,
            )
            for linea in proceso.stdout:
                fraccion = fraccion_de_progreso(linea, duracion)
                if fraccion is not None and al_progresar:
                    al_progresar(fraccion)
            codigo = proceso.wait()

        if codigo != 0:
            # Borrar el archivo a medio hacer (es nuestro, no el original).
            if salida.exists():
                salida.unlink()
            detalle = registro_errores.read_text(encoding="utf-8", errors="replace")
            ultimas = "\n".join(detalle.strip().splitlines()[-4:]) or "(sin detalle)"
            consejo = (
                "\nSi el video ya traía subtítulos de imagen, prueba desmarcando "
                "«Conservar los subtítulos que ya trae el video»."
                if conservar_existentes
                else ""
            )
            raise ErrorUnion(f"FFmpeg no pudo unir los subtítulos:\n{ultimas}{consejo}")

    return ResultadoUnion(ruta_salida=salida, pistas_agregadas=len(preparados))
