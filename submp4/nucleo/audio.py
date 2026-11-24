"""Mejorar el audio: voces más claras y efectos menos fuertes (fase 5, RF-21 a RF-27).

El problema: las películas vienen mezcladas para cine. Las explosiones son
muy fuertes y los diálogos bajos, así que al subir el volumen para entender
las voces, el siguiente efecto revienta los oídos.

La solución tiene dos partes:

1. Separar voz y efectos, cuando se puede:
   - Audio 5.1 / 7.1: los diálogos van casi siempre en el canal CENTRAL, y
     los efectos y la música en los laterales, traseros y el subwoofer (LFE).
     Al pasarlo a estéreo se le da más peso al canal central y menos al resto.
   - Audio estéreo: la voz suele estar en el centro (igual en ambos lados) y
     muchos efectos y la música están "abiertos" a los lados. Se baja la
     parte lateral (stereotools: slev), lo que realza un poco la voz.

2. Nivelar el volumen (igual para todos los casos):
   - Se bajan los graves (bass) donde retumban las explosiones, y se sube un
     poco la zona de 3 kHz (equalizer), que es la que da claridad a la voz.
   - Un compresor (acompressor) aplasta los golpes fuertes al instante.
   - Un normalizador dinámico (dynaudnorm) sube las partes bajas, como los
     diálogos susurrados, y baja las fuertes, poco a poco y sin saltos.
   - Un limitador (alimiter) asegura que nada pase del volumen máximo.

El video se copia sin tocar. Solo el audio se procesa y se guarda como una
pista NUEVA, que queda activa al abrir el video. Por defecto se conservan
también las pistas originales, para cambiar entre ellas desde el reproductor.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from submp4.nucleo.ffmpeg import (
    ErrorFFmpeg,
    buscar_ffmpeg,
    buscar_ffprobe,
    como_archivo,
    consultar_ffprobe,
    duracion_video,
    ejecutar_ffmpeg,
)
from submp4.nucleo.idiomas import nombre_de_idioma
from submp4.nucleo.rutas import ruta_sin_conflicto
from submp4.nucleo.tiempo import ms_a_texto, texto_a_ms

# Duración del fragmento de prueba, en segundos.
DURACION_PRUEBA = 120

# Calidad de la pista nueva: AAC estéreo a 192 kbps (muy buena para voces y efectos).
_BITRATE_AUDIO = "192k"


@dataclass(frozen=True)
class Nivel:
    """Parámetros de cada intensidad."""

    # Mezcla 5.1 -> estéreo: peso del canal central (voces), frontales,
    # traseros/laterales y subwoofer. Mientras más bajo el resto, más se
    # destacan las voces.
    centro: float
    frontales: float
    envolventes: float
    subwoofer: float
    nivel_lateral: float  # Solo estéreo: cuánto se conserva de los lados (1 = todo)
    graves_db: float  # Recorte de graves (explosiones, retumbos)
    claridad_db: float  # Realce de la zona de la voz (3 kHz)
    umbral_db: float  # Desde qué volumen empieza a actuar el compresor
    proporcion: float  # Cuánto comprime (4 = por cada 4 dB que suben, solo deja 1)
    ganancia_max: float  # Cuánto puede subir dynaudnorm las partes bajas (veces)


NIVELES = {
    "Suave": Nivel(1.0, 0.70, 0.50, 0.30, 0.8, -2, 1, -20, 2.5, 6),
    "Media": Nivel(1.0, 0.50, 0.35, 0.15, 0.6, -4, 2, -24, 4.0, 10),
    "Fuerte": Nivel(1.0, 0.35, 0.20, 0.00, 0.4, -6, 3, -28, 6.0, 16),
}


class ErrorAudio(Exception):
    """Error con un mensaje pensado para mostrárselo al usuario."""


# ---------------------------------------------------------------------------
# 1. Leer las pistas de audio del video
# ---------------------------------------------------------------------------

_NOMBRE_DISTRIBUCION = {1: "Mono", 2: "Estéreo", 6: "5.1", 8: "7.1"}

# Nombres genéricos que ponen los programas en las pistas y no dicen nada útil.
_NOMBRES_GENERICOS = ("handler", "iso media", "core media", "gpac", "mainconcept", "lavf")


def _titulo_util(etiquetas: dict) -> str:
    """Nombre de la pista (ej. "Latino"), ignorando nombres genéricos."""
    for clave in ("title", "handler_name"):
        valor = (etiquetas.get(clave) or "").strip()
        if valor and not any(g in valor.lower() for g in _NOMBRES_GENERICOS):
            return valor
    return ""


@dataclass(frozen=True)
class PistaAudio:
    """Una pista de audio del video, como la describe ffprobe."""

    numero: int  # Posición entre las pistas de AUDIO (0 = la primera)
    codec: str
    canales: int
    idioma: str  # Código ISO 639-2, ej. "eng"; "und" si no se sabe
    titulo: str = ""  # Ej. "Latino", "Comentarios del director"
    por_defecto: bool = False

    @property
    def es_envolvente(self) -> bool:
        """True si es 5.1 o 7.1: se puede realzar el canal central de las voces."""
        return self.canales in (6, 8)

    @property
    def distribucion(self) -> str:
        return _NOMBRE_DISTRIBUCION.get(self.canales, f"{self.canales} canales")

    def nombre_original(self) -> str:
        """Nombre para la pista original dentro del video nuevo.

        "Inglés · Original (5.1)". Si ya tenía un nombre útil, se respeta.
        """
        if self.titulo:
            return self.titulo
        return f"{nombre_de_idioma(self.idioma)} · Original ({self.distribucion})"

    def descripcion(self) -> str:
        """Texto para el menú: "Pista 1 · Inglés · 5.1 · AAC"."""
        idioma = nombre_de_idioma(self.idioma)
        partes = [f"Pista {self.numero + 1}"]
        if idioma not in self.titulo:
            partes.append(idioma)
        if self.titulo:
            partes.append(self.titulo)
        if self.distribucion not in self.titulo:
            partes.append(self.distribucion)
        partes.append(self.codec.upper())
        return " · ".join(partes)

    @property
    def ya_mejorada(self) -> bool:
        """True si es una pista que esta app ya procesó antes."""
        return "Voces mejoradas" in self.titulo


def pistas_desde_ffprobe(datos: dict) -> list[PistaAudio]:
    """Convierte la respuesta JSON de ffprobe en una lista de PistaAudio."""
    pistas = []
    for numero, stream in enumerate(datos.get("streams", [])):
        etiquetas = stream.get("tags", {})
        pistas.append(
            PistaAudio(
                numero=numero,
                codec=stream.get("codec_name", "?"),
                canales=int(stream.get("channels", 2) or 2),
                idioma=etiquetas.get("language", "und") or "und",
                titulo=_titulo_util(etiquetas),
                por_defecto=bool(stream.get("disposition", {}).get("default", 0)),
            )
        )
    return pistas


def analizar_audio(ruta_video: Path) -> list[PistaAudio]:
    """Lista las pistas de audio del video (RF-22)."""
    ruta_video = Path(ruta_video)
    if not ruta_video.is_file():
        raise ErrorAudio(f"No existe el video: {ruta_video}")
    if not buscar_ffprobe():
        raise ErrorAudio("No se encontró ffprobe (viene con FFmpeg). Revisa el README.")
    datos = consultar_ffprobe(
        ruta_video,
        ["-select_streams", "a", "-show_entries",
         "stream=codec_name,channels:stream_tags=language,title,handler_name"
         ":stream_disposition=default"],
    )
    if datos is None:
        raise ErrorAudio("No se pudo leer el video. ¿Está dañado o incompleto?")
    pistas = pistas_desde_ffprobe(datos)
    if not pistas:
        raise ErrorAudio("Este video no tiene pistas de audio.")
    return pistas


def elegir_pista(pistas: list[PistaAudio]) -> int:
    """Qué pista proponer para mejorar.

    Se prefiere una pista que no haya sido mejorada antes y, entre ellas:
    en inglés (y si hay varias, la de más canales: 5.1 da mejor resultado);
    si no hay en inglés, la que está activa; si no, la primera.
    """
    candidatas = [p for p in pistas if not p.ya_mejorada] or pistas
    en_ingles = [p for p in candidatas if p.idioma == "eng"]
    if en_ingles:
        return max(en_ingles, key=lambda p: (p.canales, -p.numero)).numero
    for pista in candidatas:
        if pista.por_defecto:
            return pista.numero
    return candidatas[0].numero


# ---------------------------------------------------------------------------
# 2. Armar los filtros (funciones puras: fáciles de probar)
# ---------------------------------------------------------------------------


def _mezcla_envolvente(canales: int, nivel: Nivel) -> str:
    """Filtro "pan" que pasa 5.1/7.1 a estéreo realzando el canal central.

    Orden estándar de los canales en FFmpeg:
        5.1: c0 FL, c1 FR, c2 FC (voces), c3 LFE, c4 y c5 traseros/laterales.
        7.1: igual, más c6 y c7 laterales.
    El "<" hace que los pesos se ajusten para que la suma no sature.
    """
    izquierdos, derechos = [4], [5]
    if canales == 8:
        izquierdos, derechos = [4, 6], [5, 7]

    def lado(frontal: int, envolventes: list[int]) -> str:
        partes = [f"{nivel.centro}*c2", f"{nivel.frontales}*c{frontal}"]
        partes += [f"{nivel.envolventes}*c{c}" for c in envolventes]
        if nivel.subwoofer:
            partes.append(f"{nivel.subwoofer}*c3")
        return "+".join(partes)

    return f"pan=stereo|FL<{lado(0, izquierdos)}|FR<{lado(1, derechos)}"


def construir_filtro(canales: int, nombre_nivel: str = "Media") -> str:
    """Cadena de filtros de FFmpeg para mejorar las voces (RF-23, RF-24)."""
    if nombre_nivel not in NIVELES:
        raise ErrorAudio(f"Intensidad desconocida: {nombre_nivel!r}")
    nivel = NIVELES[nombre_nivel]

    filtros = []
    if canales in (6, 8):
        filtros.append(_mezcla_envolvente(canales, nivel))
    elif canales == 2:
        filtros.append(f"stereotools=slev={nivel.nivel_lateral}")
    elif canales > 2:
        # Distribuciones raras (3, 4, 5, 7 canales): mezcla estándar a estéreo.
        filtros.append("aformat=channel_layouts=stereo")
    # Mono (1 canal): no hay lados que separar; solo se nivela.

    filtros += [
        f"bass=g={nivel.graves_db}:f=120",
        f"equalizer=f=3000:t=q:w=1:g={nivel.claridad_db}",
        f"acompressor=threshold={nivel.umbral_db}dB:ratio={nivel.proporcion}"
        ":attack=5:release=250",
        f"dynaudnorm=f=250:g=15:p=0.9:m={nivel.ganancia_max}",
        "alimiter=limit=-1dB:level=disabled",
        "aresample=48000",
    ]
    return ",".join(filtros)


def construir_comando(
    ffmpeg: str,
    ruta_video: Path,
    pista: PistaAudio,
    filtro: str,
    nombre_pista: str,
    ruta_salida: Path,
    conservar_originales: bool = True,
    inicio_ms: int | None = None,
    duracion_s: float | None = None,
    originales: list[PistaAudio] | None = None,
) -> list[str]:
    """Arma la lista de argumentos para FFmpeg.

    Pistas de salida: video (copiado), audio mejorado (pista 1, activa),
    audios originales (copiados, si se conservan) y subtítulos (copiados).
    inicio_ms / duracion_s: para procesar solo un fragmento de prueba.
    originales: todas las pistas de audio del video, para ponerles nombre.
    """
    comando = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-n"]
    if inicio_ms is not None:
        comando += ["-ss", f"{inicio_ms / 1000:.3f}"]  # Antes de -i: salto rápido
    comando += ["-i", como_archivo(ruta_video)]
    if duracion_s is not None:
        comando += ["-t", f"{duracion_s:.3f}"]

    comando += ["-map", "0:v?", "-map", f"0:a:{pista.numero}"]
    if conservar_originales:
        comando += ["-map", "0:a"]
    comando += ["-map", "0:s?"]

    # Todo se copia tal cual, excepto la pista nueva (la primera de audio).
    comando += ["-c", "copy"]
    comando += ["-filter:a:0", filtro, "-c:a:0", "aac", "-b:a:0", _BITRATE_AUDIO, "-ac:a:0", "2"]
    comando += ["-metadata:s:a:0", f"language={pista.idioma}"]
    comando += ["-metadata:s:a:0", f"handler_name={nombre_pista}"]
    comando += ["-metadata:s:a:0", f"title={nombre_pista}"]
    if conservar_originales and originales:
        # La pista original número k queda como pista de audio k+1 en la salida.
        for original in originales:
            nombre = original.nombre_original()
            comando += [f"-metadata:s:a:{original.numero + 1}", f"handler_name={nombre}"]
            comando += [f"-metadata:s:a:{original.numero + 1}", f"title={nombre}"]

    # La pista mejorada queda activa; las originales, disponibles en el menú.
    comando += ["-disposition:a", "0", "-disposition:a:0", "default"]

    comando += ["-progress", "pipe:1", "-nostats"]
    comando.append(como_archivo(ruta_salida))
    return comando


# ---------------------------------------------------------------------------
# 3. Funciones principales
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResultadoAudio:
    """Resumen de la mejora, para mostrarlo en la ventana."""

    ruta_salida: Path
    pista: PistaAudio
    nivel: str
    conservo_originales: bool

    @property
    def metodo(self) -> str:
        if self.pista.es_envolvente:
            return f"{self.pista.distribucion}: se realzó el canal central de las voces"
        if self.pista.canales == 2:
            return "Estéreo: se redujeron los sonidos de los lados y se niveló el volumen"
        return "Se niveló el volumen"


def ruta_audio_disponible(ruta_video: Path, prueba: bool = False) -> Path:
    """"Pelicula.mp4" -> "Pelicula.audio.mp4" (o "Pelicula.audio-prueba.mp4")."""
    ruta_video = Path(ruta_video)
    sufijo = "audio-prueba" if prueba else "audio"
    return ruta_sin_conflicto(ruta_video.with_name(f"{ruta_video.stem}.{sufijo}{ruta_video.suffix}"))


def _preparar(ruta_video: Path, numero_pista: int | None, nivel: str):
    ruta_video = Path(ruta_video)
    if ruta_video.suffix.lower() != ".mp4":
        raise ErrorAudio("El video debe ser un archivo .mp4")
    if nivel not in NIVELES:
        raise ErrorAudio(f"Intensidad desconocida: {nivel!r}")
    ffmpeg = buscar_ffmpeg()
    if not ffmpeg:
        raise ErrorAudio("FFmpeg no está instalado. Revisa el README para instalarlo.")

    pistas = analizar_audio(ruta_video)
    if numero_pista is None:
        numero_pista = elegir_pista(pistas)
    if not 0 <= numero_pista < len(pistas):
        raise ErrorAudio("La pista de audio elegida no existe en este video.")
    return ruta_video, ffmpeg, pistas, pistas[numero_pista]


def _procesar(
    ffmpeg, ruta_video, pistas, pista, nivel, salida, conservar, al_progresar, inicio_ms, duracion_s
) -> ResultadoAudio:
    if Path(salida).resolve() == ruta_video.resolve():
        raise ErrorAudio("La salida no puede ser el mismo video original.")
    nombre_pista = f"{nombre_de_idioma(pista.idioma)} · Voces mejoradas ({nivel})"
    comando = construir_comando(
        ffmpeg, ruta_video, pista, construir_filtro(pista.canales, nivel), nombre_pista,
        salida, conservar, inicio_ms, duracion_s, pistas,
    )
    duracion = duracion_s if duracion_s is not None else duracion_video(ruta_video)
    try:
        ejecutar_ffmpeg(comando, salida, duracion, al_progresar)
    except ErrorFFmpeg as error:
        raise ErrorAudio(f"FFmpeg no pudo mejorar el audio:\n{error.detalle}") from None
    return ResultadoAudio(Path(salida), pista, nivel, conservar)


def mejorar_audio(
    ruta_video: Path,
    nivel: str = "Media",
    numero_pista: int | None = None,
    conservar_originales: bool = True,
    al_progresar: Callable[[float], None] | None = None,
    ruta_salida: Path | None = None,
) -> ResultadoAudio:
    """Crea "Pelicula.audio.mp4" con una pista de voces mejoradas (RF-21).

    numero_pista: qué pista de audio mejorar (0 = la primera). Si es None,
    se elige sola (la primera en inglés, si hay).
    """
    ruta_video, ffmpeg, pistas, pista = _preparar(ruta_video, numero_pista, nivel)
    salida = Path(ruta_salida) if ruta_salida else ruta_audio_disponible(ruta_video)
    return _procesar(
        ffmpeg, ruta_video, pistas, pista, nivel, salida, conservar_originales,
        al_progresar, None, None,
    )


def probar_fragmento(
    ruta_video: Path,
    inicio: str,
    nivel: str = "Media",
    numero_pista: int | None = None,
    al_progresar: Callable[[float], None] | None = None,
    ruta_salida: Path | None = None,
) -> ResultadoAudio:
    """Mejora solo 2 minutos, desde `inicio` (ej. "00:45:00"), para escuchar antes (RF-26).

    El fragmento conserva el audio original como segunda pista, para comparar
    ambas en el reproductor.
    """
    try:
        inicio_ms = texto_a_ms(inicio)
    except ValueError as error:
        raise ErrorAudio(str(error)) from None

    ruta_video, ffmpeg, pistas, pista = _preparar(ruta_video, numero_pista, nivel)
    total = duracion_video(ruta_video)
    if total is not None and inicio_ms / 1000 >= total:
        dura = ms_a_texto(round(total * 1000)).split(",")[0]  # Sin milisegundos
        raise ErrorAudio(f"El video dura {dura}: elige un inicio anterior.")
    duracion_s = float(DURACION_PRUEBA)
    if total is not None:
        duracion_s = min(duracion_s, total - inicio_ms / 1000)

    salida = Path(ruta_salida) if ruta_salida else ruta_audio_disponible(ruta_video, prueba=True)
    return _procesar(
        ffmpeg, ruta_video, pistas, pista, nivel, salida, True, al_progresar, inicio_ms, duracion_s
    )
