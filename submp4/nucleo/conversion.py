"""Convertir cualquier formato de subtítulo a SRT (fase 1).

Ya está la lista de formatos soportados. La conversión con limpieza
de ASS se implementa en la fase 1 (ver RF-01 a RF-04 en REQUISITOS.md).
"""

from pathlib import Path

# Extensión del archivo -> nombre del formato que entiende pysubs2.
FORMATOS_ENTRADA = {
    ".srt": "srt",
    ".ass": "ass",
    ".ssa": "ssa",
    ".vtt": "vtt",
    ".sub": "microdvd",
    ".mpl": "mpl2",
    ".txt": "tmp",
}


def es_formato_soportado(ruta: Path) -> bool:
    """Indica si la app sabe leer este archivo, según su extensión."""
    return Path(ruta).suffix.lower() in FORMATOS_ENTRADA


def convertir_a_srt(ruta_entrada: Path, ruta_salida: Path, fps: float | None = None) -> None:
    """Convierte un subtítulo a SRT en UTF-8, limpiando estilos y efectos.

    PENDIENTE (fase 1):
      - Leer con codificacion.leer_texto y pysubs2.
      - Quitar etiquetas {\\...}, pasar {\\i1}/{\\b1} a <i>/<b>.
      - Quitar dibujos {\\p1}, letreros y karaoke automáticamente.
      - Fusionar diálogos simultáneos.
    """
    raise NotImplementedError("Disponible en la fase 1.")
