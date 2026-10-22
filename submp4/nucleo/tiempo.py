"""Convertir tiempos escritos por el usuario a milisegundos y viceversa.

Internamente la app trabaja siempre en **milisegundos** (números enteros),
porque es lo que usa la librería pysubs2 y evita errores de redondeo.

Formatos aceptados (RF-08):
    "83"            -> 83 segundos
    "1:23"          -> 1 minuto 23 segundos
    "00:01:23"      -> 1 minuto 23 segundos
    "00:00:6"       -> 6 segundos
    "00:01:23,500"  -> 1 minuto 23,5 segundos (sirve coma o punto)
"""

import re

# Expresión regular que separa horas, minutos y segundos.
#   (?:(\d+):)?   -> horas opcionales, seguidas de ":"
#   (\d+):        -> minutos, seguidos de ":"  (todo el bloque es opcional)
#   (\d+(?:[.,]\d+)?) -> segundos, con decimales opcionales
_PATRON_TIEMPO = re.compile(r"^\s*(?:(?:(\d+):)?(\d+):)?(\d+(?:[.,]\d+)?)\s*$")


def texto_a_ms(texto: str) -> int:
    """Convierte un tiempo como "00:01:23" en milisegundos (83000).

    Lanza ValueError con un mensaje claro si el texto no es válido.
    """
    coincidencia = _PATRON_TIEMPO.match(texto)
    if not coincidencia:
        raise ValueError(
            f"Tiempo no válido: {texto!r}. Usa HH:MM:SS, MM:SS o segundos "
            "(ej. 00:01:23 o 83)."
        )

    horas, minutos, segundos = coincidencia.groups()
    segundos_num = float(segundos.replace(",", "."))

    # Si el usuario escribió minutos, los segundos no pueden pasar de 59.
    if minutos is not None and segundos_num >= 60:
        raise ValueError(f"Los segundos deben ser menores a 60 en {texto!r}.")
    # Si escribió horas, los minutos no pueden pasar de 59.
    if horas is not None and int(minutos) >= 60:
        raise ValueError(f"Los minutos deben ser menores a 60 en {texto!r}.")

    total_segundos = int(horas or 0) * 3600 + int(minutos or 0) * 60 + segundos_num
    return round(total_segundos * 1000)


def texto_con_signo_a_ms(texto: str) -> int:
    """Como texto_a_ms, pero acepta un signo delante: "+2.5" o "-1,5".

    Se usa para el desplazamiento (RF-05): positivo atrasa el subtítulo
    (aparece más tarde) y negativo lo adelanta (aparece antes).
    """
    limpio = texto.strip()
    signo = 1
    if limpio.startswith(("+", "-")):
        signo = -1 if limpio[0] == "-" else 1
        limpio = limpio[1:]
    return signo * texto_a_ms(limpio)


def ms_a_texto(ms: int) -> str:
    """Convierte milisegundos en texto legible: 83500 -> "00:01:23,500".

    Si es negativo, le pone el signo "-" delante.
    """
    signo = "-" if ms < 0 else ""
    ms = abs(int(ms))
    horas, resto = divmod(ms, 3_600_000)
    minutos, resto = divmod(resto, 60_000)
    segundos, milis = divmod(resto, 1000)
    return f"{signo}{horas:02d}:{minutos:02d}:{segundos:02d},{milis:03d}"
