"""Unir subtítulos SRT a un video MP4 usando FFmpeg (fase 3).

SEGURIDAD (RNF-03): FFmpeg se llamará con subprocess pasando una LISTA de
argumentos y sin shell=True. Así un nombre de archivo raro como
'pelicula"; del *.mp4' nunca se interpreta como un comando.
"""

import shutil
from pathlib import Path


def buscar_ffmpeg() -> str | None:
    """Devuelve la ruta de FFmpeg si está instalado, o None si no (RF-16)."""
    return shutil.which("ffmpeg")


def ruta_salida_disponible(ruta_video: Path) -> Path:
    """Calcula dónde guardar el video con subtítulos sin pisar nada (RF-12).

    "Pelicula.mp4" -> "Pelicula.subs.mp4"
    Si ya existe   -> "Pelicula.subs (2).mp4", "Pelicula.subs (3).mp4"…
    """
    ruta_video = Path(ruta_video)
    base = ruta_video.with_name(f"{ruta_video.stem}.subs{ruta_video.suffix}")
    if not base.exists():
        return base

    numero = 2
    while True:
        candidata = ruta_video.with_name(
            f"{ruta_video.stem}.subs ({numero}){ruta_video.suffix}"
        )
        if not candidata.exists():
            return candidata
        numero += 1


def unir_subtitulos(ruta_video: Path, pistas: list[tuple[Path, str]]) -> Path:
    """Une una o varias pistas SRT al MP4, sin recodificar (RF-10, RF-11).

    pistas: lista de (ruta_srt, idioma), ej. [(Path("en.srt"), "eng")].

    PENDIENTE (fase 3).
    """
    raise NotImplementedError("Disponible en la fase 3.")
