"""Convertir cualquier formato de subtítulo a SRT limpio en UTF-8 (fase 1).

Pasos de la conversión (RF-01 a RF-04 en REQUISITOS.md):
    1. Leer el archivo detectando su codificación (ñ, tildes).
    2. Leer el formato con pysubs2 (ASS, SSA, VTT, SUB, SRT…).
    3. Quitar automáticamente letreros, karaoke y dibujos.
    4. Limpiar las etiquetas de estilo y dejar solo <i>, <b> y <u>.
    5. Fusionar los diálogos que se pisan en el tiempo, porque el MP4
       no puede mostrar dos subtítulos superpuestos.
    6. Guardar el SRT en UTF-8 en un archivo NUEVO.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import pysubs2
from pysubs2.exceptions import FormatAutodetectionError, Pysubs2Error, UnknownFPSError
from pysubs2.formats import autodetect_format

from submp4.nucleo.codificacion import leer_texto
from submp4.nucleo.rutas import ruta_sin_conflicto
from submp4.nucleo.tiempo import ms_a_texto

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


class ErrorConversion(Exception):
    """Error con un mensaje pensado para mostrárselo al usuario."""


@dataclass(frozen=True)
class Linea:
    """Una línea de subtítulo ya limpia. Tiempos en milisegundos."""

    inicio: int
    fin: int
    texto: str


@dataclass(frozen=True)
class ResultadoConversion:
    """Resumen de la conversión, para mostrarlo en la ventana."""

    ruta_salida: Path
    formato_origen: str
    codificacion_origen: str
    lineas_leidas: int
    efectos_quitados: int
    lineas_guardadas: int


def es_formato_soportado(ruta: Path) -> bool:
    """Indica si la app sabe leer este archivo, según su extensión."""
    return Path(ruta).suffix.lower() in FORMATOS_ENTRADA


# ---------------------------------------------------------------------------
# 1. Detectar letreros, karaoke y efectos (RF-03, "quitar automáticamente")
# ---------------------------------------------------------------------------

# Palabras con las que suelen EMPEZAR los nombres de estilos de efectos.
# Ej.: "Signs", "Song_Romaji", "Karaoke", "Title", "Typeset", "Insert".
_PREFIJOS_EFECTO = ("sign", "song", "kara", "lyric", "title", "typeset", "insert")

# Nombres cortos que también son efectos: "OP", "ED2", "TS", "FX".
_NOMBRE_CORTO_EFECTO = re.compile(r"^(op|ed|ts|fx)\d*$")


def es_estilo_de_efecto(nombre_estilo: str) -> bool:
    """True si el nombre del estilo indica letreros, canciones o karaoke.

    Se separa el nombre en palabras ("OP_Romaji" -> ["op", "romaji"]) para
    no confundir, por ejemplo, "Top" con "OP".
    """
    palabras = re.split(r"[^a-z0-9]+", nombre_estilo.lower())
    return any(
        palabra.startswith(_PREFIJOS_EFECTO) or _NOMBRE_CORTO_EFECTO.match(palabra)
        for palabra in palabras
        if palabra
    )


# Etiquetas que casi siempre son de karaoke: {\k20}, {\kf30}, {\ko10}, {\K15}.
_KARAOKE = re.compile(r"\\[kK][fo]?\d")
# Etiquetas de letreros animados o deformados: movimiento, recortes,
# animaciones, rotaciones y cizallamiento.
_LETRERO = re.compile(r"\\(move\(|i?clip\(|t\(|org\(|fr[xyz]?-?\d|fa[xy]-?\d)")
# \pos solo cuenta como letrero si viene con estilos de tipografía
# (fuente, tamaño, color, borde…). Un diálogo puesto arriba con solo
# {\pos(...)} o {\an8} se conserva.
_POSICION = re.compile(r"\\pos\(")
_TIPOGRAFIA = re.compile(r"\\(fn|fs\d|fsc[xy]|blur|bord|be\d|[1-4]?c&)")


def es_linea_de_efecto(evento: pysubs2.SSAEvent) -> bool:
    """True si la línea es un dibujo, karaoke o letrero (no un diálogo)."""
    texto = evento.text
    if evento.is_drawing:  # Dibujos vectoriales {\p1} m 0 0 l ...
        return True
    if evento.effect.strip():  # Campo "Effect" del ASS (Banner, Scroll…)
        return True
    if _KARAOKE.search(texto) or _LETRERO.search(texto):
        return True
    return bool(_POSICION.search(texto) and _TIPOGRAFIA.search(texto))


# ---------------------------------------------------------------------------
# 2. Pasar el texto de formato ASS a texto SRT
# ---------------------------------------------------------------------------

_BLOQUE_ETIQUETAS = re.compile(r"\{([^}]*)\}")  # Todo lo que va entre { }
# Cursiva \i1, negrita \b1 (o \b700) y subrayado \u1. Se exige un número
# justo después para no confundirse con \bord, \blur, \be o \iclip.
_FORMATO = re.compile(r"\\([ibu])(\d+)")
_ETIQUETA_SRT = re.compile(r"</?[ibu]>")
_ETIQUETA_VACIA = re.compile(r"<([ibu])>(\s*)</\1>")


def _formato_activo(letra: str, valor: str) -> bool:
    numero = int(valor)
    if letra == "b":
        # \b1 es negrita; \b100…\b900 son grosores y solo 700+ es negrita.
        return numero == 1 or numero >= 700
    return numero != 0


def texto_ass_a_srt(texto: str, italica: bool = False, negrita: bool = False) -> str:
    """Convierte el texto de una línea ASS en texto SRT limpio.

    italica / negrita: si el ESTILO de la línea ya es cursiva o negrita,
    toda la línea queda envuelta en <i> o <b>.

    Ej.: r"{\\an8\\i1}Hola{\\i0}\\NMundo" -> "<i>Hola</i>\\nMundo"
    """
    estado = {"i": italica, "b": negrita, "u": False}
    partes = [f"<{letra}>" for letra, activo in estado.items() if activo]

    posicion = 0
    for bloque in _BLOQUE_ETIQUETAS.finditer(texto):
        partes.append(texto[posicion : bloque.start()])  # Texto normal
        for letra, valor in _FORMATO.findall(bloque.group(1)):
            nuevo = _formato_activo(letra, valor)
            if nuevo != estado[letra]:
                partes.append(f"<{letra}>" if nuevo else f"</{letra}>")
                estado[letra] = nuevo
        # El resto de etiquetas del bloque ({\an8}, {\fad}, {\c}…) se descarta.
        posicion = bloque.end()
    partes.append(texto[posicion:])

    # Cerrar las etiquetas que quedaron abiertas, en orden inverso.
    for letra in reversed(list(estado)):
        if estado[letra]:
            partes.append(f"</{letra}>")

    resultado = "".join(partes)
    resultado = resultado.replace(r"\N", "\n").replace(r"\n", "\n").replace(r"\h", " ")
    resultado = _ETIQUETA_VACIA.sub(r"\2", resultado)

    # Quitar espacios sobrantes y renglones vacíos.
    renglones = [renglon.strip() for renglon in resultado.split("\n")]
    renglones = [r for r in renglones if _ETIQUETA_SRT.sub("", r).strip()]
    return "\n".join(renglones)


# ---------------------------------------------------------------------------
# 3. Fusionar diálogos superpuestos
# ---------------------------------------------------------------------------


def aplanar_superposiciones(lineas: list[Linea]) -> list[Linea]:
    """Convierte líneas que se pisan en tramos sin superposición.

    Ej.: A de 0 a 4 s y B de 2 a 6 s quedan así:
         0–2 s: "A"   2–4 s: "A\\nB"   4–6 s: "B"

    Así el MP4 muestra todo lo que se dice, sin que una línea tape a otra.
    """
    validas = sorted(
        (linea for linea in lineas if linea.fin > linea.inicio),
        key=lambda linea: (linea.inicio, linea.fin),
    )
    limites = sorted({t for linea in validas for t in (linea.inicio, linea.fin)})

    resultado: list[Linea] = []
    activas: list[Linea] = []
    siguiente = 0
    for t0, t1 in zip(limites, limites[1:]):
        # Agregar las líneas que empiezan en este momento…
        while siguiente < len(validas) and validas[siguiente].inicio <= t0:
            activas.append(validas[siguiente])
            siguiente += 1
        # …y sacar las que ya terminaron.
        activas = [linea for linea in activas if linea.fin > t0]
        if not activas:
            continue

        # Unir los textos activos sin repetir (algunos archivos duplican líneas).
        textos = list(dict.fromkeys(linea.texto for linea in activas))
        texto = "\n".join(textos)

        anterior = resultado[-1] if resultado else None
        if anterior and anterior.fin == t0 and anterior.texto == texto:
            resultado[-1] = Linea(anterior.inicio, t1, texto)  # Extender tramo
        else:
            resultado.append(Linea(t0, t1, texto))
    return resultado


# ---------------------------------------------------------------------------
# 4. Escribir el SRT
# ---------------------------------------------------------------------------


def generar_srt(lineas: list[Linea]) -> str:
    """Arma el texto completo de un archivo SRT."""
    bloques = []
    for numero, linea in enumerate(lineas, start=1):
        inicio = ms_a_texto(max(0, linea.inicio))
        fin = ms_a_texto(max(0, linea.fin))
        bloques.append(f"{numero}\n{inicio} --> {fin}\n{linea.texto}\n")
    return "\n".join(bloques)


def ruta_srt_disponible(ruta_entrada: Path) -> Path:
    """Dónde guardar el SRT sin pisar nada (RNF-02).

    "Serie.ass" -> "Serie.srt"
    "Serie.srt" -> "Serie.convertido.srt" (nunca se reemplaza el original)
    Si ya existe -> "Serie (2).srt", "Serie (3).srt"…
    """
    ruta_entrada = Path(ruta_entrada)
    if ruta_entrada.suffix.lower() == ".srt":
        deseada = ruta_entrada.with_name(f"{ruta_entrada.stem}.convertido.srt")
    else:
        deseada = ruta_entrada.with_suffix(".srt")
    return ruta_sin_conflicto(deseada)


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------


def _cargar_subtitulo(texto: str, ruta: Path, fps: float | None) -> tuple[pysubs2.SSAFile, str]:
    """Detecta el formato y lo lee con pysubs2. Devuelve (subtítulos, formato)."""
    try:
        formato = autodetect_format(texto)
    except FormatAutodetectionError:
        # Si el contenido no basta para saberlo, usamos la extensión.
        formato = FORMATOS_ENTRADA.get(ruta.suffix.lower())
        if formato is None:
            raise ErrorConversion(
                "No reconozco el formato de este archivo. Formatos aceptados: "
                + ", ".join(sorted(FORMATOS_ENTRADA))
            ) from None

    opciones = {"fps": fps} if formato == "microdvd" else {}
    try:
        return pysubs2.SSAFile.from_string(texto, format_=formato, **opciones), formato
    except UnknownFPSError:
        raise ErrorConversion(
            "Este archivo mide el tiempo en cuadros (frames). Escribe los FPS "
            "del video, por ejemplo 23.976 o 25."
        ) from None
    except (Pysubs2Error, ValueError) as error:
        raise ErrorConversion(f"No se pudo leer el subtítulo: {error}") from None


def convertir_a_srt(
    ruta_entrada: Path, ruta_salida: Path | None = None, fps: float | None = None
) -> ResultadoConversion:
    """Convierte un subtítulo a SRT limpio en UTF-8 y lo guarda en un archivo nuevo.

    ruta_salida: si no se indica, se calcula con ruta_srt_disponible().
    fps: solo para formatos por cuadros (MicroDVD .sub) sin FPS en el archivo.
    """
    ruta_entrada = Path(ruta_entrada)
    if not ruta_entrada.is_file():
        raise ErrorConversion(f"No existe el archivo: {ruta_entrada}")

    texto, codificacion = leer_texto(ruta_entrada)
    subtitulos, formato = _cargar_subtitulo(texto, ruta_entrada, fps)

    leidas = efectos = 0
    lineas: list[Linea] = []
    for evento in subtitulos.events:
        if evento.is_comment:  # Comentarios del ASS: no se muestran nunca.
            continue
        leidas += 1
        if es_estilo_de_efecto(evento.style) or es_linea_de_efecto(evento):
            efectos += 1
            continue

        estilo = subtitulos.styles.get(evento.style)
        texto_srt = texto_ass_a_srt(
            evento.text,
            italica=bool(estilo and estilo.italic),
            negrita=bool(estilo and estilo.bold),
        )
        if texto_srt:
            lineas.append(Linea(evento.start, evento.end, texto_srt))

    finales = aplanar_superposiciones(lineas)

    salida = Path(ruta_salida) if ruta_salida else ruta_srt_disponible(ruta_entrada)
    if salida.resolve() == ruta_entrada.resolve():
        raise ErrorConversion("La salida no puede ser el mismo archivo original.")
    # newline="\r\n": saltos de línea de Windows, los más compatibles en SRT.
    salida.write_text(generar_srt(finales), encoding="utf-8", newline="\r\n")

    return ResultadoConversion(
        ruta_salida=salida,
        formato_origen=formato,
        codificacion_origen=codificacion,
        lineas_leidas=leidas,
        efectos_quitados=efectos,
        lineas_guardadas=len(finales),
    )
