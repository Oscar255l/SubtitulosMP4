"""Idiomas de las pistas (subtítulos y audio) dentro del MP4."""

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

# Otros códigos que a veces traen los videos (ISO 639-2/B y /T).
_OTROS = {"fra": "Francés", "deu": "Alemán", "kor": "Coreano", "chi": "Chino", "zho": "Chino",
          "rus": "Ruso", "en": "Inglés", "es": "Español"}


def nombre_de_idioma(codigo: str | None) -> str:
    """"spa" -> "Español". Si no lo conoce, devuelve el código tal cual."""
    if not codigo:
        return "Sin especificar"
    for nombre, valor in IDIOMAS.items():
        if valor == codigo:
            return nombre
    return _OTROS.get(codigo, codigo)
