"""Subtítulo bilingüe: inglés arriba y español en cursiva debajo (fase 4).

Ejemplo de cómo se ve en pantalla:

    Are you coming tonight?
    ¿Vienes esta noche?        <- en cursiva

El problema: los dos subtítulos casi nunca tienen exactamente los mismos
tiempos, y a veces una frase en inglés está partida en dos en español.
Si solo se juntaran los textos que coinciden al milisegundo, la
traducción parpadearía. Por eso cada línea en español se asigna a la
línea en inglés con la que más tiempo comparte en pantalla, y se muestra
durante todo el tiempo de la línea en inglés.
"""

import re
from bisect import bisect_left

from submp4.nucleo.conversion import Linea, aplanar_superposiciones

_ETIQUETA_CURSIVA = re.compile(r"</?i>")


def en_cursiva(texto: str) -> str:
    """Pone cada renglón en cursiva sin duplicar etiquetas <i> que ya tuviera."""
    return "\n".join(
        f"<i>{_ETIQUETA_CURSIVA.sub('', renglon)}</i>" for renglon in texto.split("\n")
    )


def _superposicion(a: Linea, b: Linea) -> int:
    """Cuántos milisegundos se ven a la vez dos líneas (0 si no se tocan)."""
    return max(0, min(a.fin, b.fin) - max(a.inicio, b.inicio))


def combinar_bilingue(principal: list[Linea], traduccion: list[Linea]) -> list[Linea]:
    """Combina dos subtítulos en uno: principal arriba, traducción en cursiva.

    principal / traduccion: líneas ya limpias y sin superposiciones (como
    las devuelve conversion.leer_lineas).

    - Cada línea de la traducción se pega a la línea principal con la que
      más tiempo comparte.
    - Si una línea de la traducción no coincide con ninguna principal
      (ej. el subtítulo en inglés no tiene esa frase), se muestra sola.
    """
    principal = sorted(principal, key=lambda linea: linea.inicio)
    inicios = [linea.inicio for linea in principal]
    asignadas: dict[int, list[Linea]] = {indice: [] for indice in range(len(principal))}
    sueltas: list[Linea] = []

    for linea_traduccion in sorted(traduccion, key=lambda linea: linea.inicio):
        # Candidatas: líneas principales que empiezan antes de que la
        # traducción termine. Se revisan hacia atrás mientras se toquen.
        mejor, mejor_tiempo = None, 0
        indice = bisect_left(inicios, linea_traduccion.fin) - 1
        while indice >= 0 and principal[indice].fin > linea_traduccion.inicio:
            tiempo = _superposicion(principal[indice], linea_traduccion)
            if tiempo > mejor_tiempo:
                mejor, mejor_tiempo = indice, tiempo
            indice -= 1

        if mejor is None:
            sueltas.append(linea_traduccion)
        else:
            asignadas[mejor].append(linea_traduccion)

    resultado = []
    for indice, linea_principal in enumerate(principal):
        traducciones = list(dict.fromkeys(t.texto for t in asignadas[indice]))
        texto = linea_principal.texto
        if traducciones:
            texto += "\n" + "\n".join(en_cursiva(t) for t in traducciones)
        resultado.append(Linea(linea_principal.inicio, linea_principal.fin, texto))

    resultado += [Linea(t.inicio, t.fin, en_cursiva(t.texto)) for t in sueltas]
    return aplanar_superposiciones(resultado)
