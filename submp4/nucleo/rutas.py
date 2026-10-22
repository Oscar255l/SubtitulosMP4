"""Calcular rutas de salida sin pisar archivos que ya existen (RNF-02)."""

from pathlib import Path


def ruta_sin_conflicto(ruta_deseada: Path) -> Path:
    """Devuelve ruta_deseada si está libre; si no, le agrega " (2)", " (3)"…

    "Pelicula.subs.mp4" ocupado -> "Pelicula.subs (2).mp4"
    """
    ruta_deseada = Path(ruta_deseada)
    if not ruta_deseada.exists():
        return ruta_deseada

    numero = 2
    while True:
        candidata = ruta_deseada.with_name(
            f"{ruta_deseada.stem} ({numero}){ruta_deseada.suffix}"
        )
        if not candidata.exists():
            return candidata
        numero += 1
