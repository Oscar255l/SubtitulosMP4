"""Leer archivos de subtítulos sin que la ñ y las tildes salgan dañadas (RF-02).

Muchos subtítulos en español están guardados en Windows-1252 o Latin-1, no
en UTF-8. Si se leen mal aparecen cosas como "AÃ±o" en vez de "Año".
"""

from pathlib import Path

# Marcas al inicio del archivo (BOM) que indican UTF-16.
_BOM_UTF16 = (b"\xff\xfe", b"\xfe\xff")

# Orden en que se prueban las codificaciones. "utf-8-sig" también quita el
# BOM de UTF-8 si existe. "latin-1" nunca falla, por eso va de último.
CODIFICACIONES = ("utf-8-sig", "cp1252", "latin-1")


def decodificar(datos: bytes) -> tuple[str, str]:
    """Convierte bytes en texto. Devuelve (texto, codificación_usada)."""
    if datos.startswith(_BOM_UTF16):
        return datos.decode("utf-16"), "utf-16"

    for codificacion in CODIFICACIONES:
        try:
            return datos.decode(codificacion), codificacion
        except UnicodeDecodeError:
            continue  # No era esta, probamos la siguiente.

    # No debería llegar aquí porque latin-1 acepta cualquier byte.
    raise ValueError("No se pudo leer la codificación del archivo.")


def leer_texto(ruta: Path) -> tuple[str, str]:
    """Lee un archivo de subtítulos. Devuelve (texto, codificación_usada)."""
    return decodificar(Path(ruta).read_bytes())
