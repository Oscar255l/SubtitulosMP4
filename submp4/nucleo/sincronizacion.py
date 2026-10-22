"""Sincronizar subtítulos con el video (fase 2, RF-05 a RF-09).

Tres formas de calcular el ajuste:
    - Por segundos:    "+2.5" -> todo aparece 2,5 s más tarde.
    - Por un punto:    "el subtítulo empieza en 00:00:06 y hablan en 00:01:23".
    - Por dos puntos:  una línea del inicio y otra del final, para corregir
                       subtítulos que se van desfasando (diferencia de FPS).

Las tres producen un AjusteLineal, que luego se aplica a todo el archivo.
El resultado siempre se guarda como SRT en un archivo NUEVO.
"""

from dataclasses import dataclass
from pathlib import Path

from submp4.nucleo.conversion import Linea, guardar_srt, leer_lineas
from submp4.nucleo.rutas import ruta_sin_conflicto
from submp4.nucleo.tiempo import ms_a_texto, texto_a_ms, texto_con_signo_a_ms

# ---------------------------------------------------------------------------
# 1. Calcular el ajuste
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AjusteLineal:
    """Ajuste de la forma: tiempo_nuevo = tiempo_viejo * factor + desplazamiento.

    - factor = 1.0 significa que no se estira ni se encoge.
    - factor distinto de 1 corrige subtítulos hechos para otros FPS.
    """

    factor: float
    desplazamiento_ms: float

    def aplicar(self, tiempo_ms: int) -> int:
        """Devuelve el tiempo corregido, en milisegundos."""
        return round(tiempo_ms * self.factor + self.desplazamiento_ms)

    @property
    def estira(self) -> bool:
        """True si el ajuste cambia la velocidad (no solo mueve)."""
        return abs(self.factor - 1.0) > 1e-9

    @property
    def sin_cambios(self) -> bool:
        """True si aplicar el ajuste no movería nada."""
        return not self.estira and round(self.desplazamiento_ms) == 0


def desplazamiento_por_punto(inicio_subtitulo: str, inicio_dialogo: str) -> int:
    """Calcula cuántos milisegundos hay que mover el subtítulo (RF-06).

    Ejemplo: el subtítulo empieza en "00:00:06" pero el diálogo empieza en
    "00:01:23" -> hay que atrasarlo 77 segundos -> devuelve 77000.
    Un resultado negativo significa que hay que adelantarlo.
    """
    return texto_a_ms(inicio_dialogo) - texto_a_ms(inicio_subtitulo)


def ajuste_por_segundos(texto: str) -> AjusteLineal:
    """Ajuste por segundos (RF-05): "+2.5" atrasa, "-1,5" adelanta."""
    return AjusteLineal(factor=1.0, desplazamiento_ms=texto_con_signo_a_ms(texto))


def ajuste_por_punto(inicio_subtitulo: str, inicio_dialogo: str) -> AjusteLineal:
    """Ajuste por un punto (RF-06)."""
    return AjusteLineal(
        factor=1.0,
        desplazamiento_ms=desplazamiento_por_punto(inicio_subtitulo, inicio_dialogo),
    )


def ajuste_por_dos_puntos(
    sub_1: str, real_1: str, sub_2: str, real_2: str
) -> AjusteLineal:
    """Calcula el ajuste a partir de dos puntos (RF-07).

    sub_1 / sub_2:   cuándo aparecen dos líneas en el subtítulo actual.
    real_1 / real_2: cuándo se dicen esas líneas en el video.

    Lo ideal es elegir una línea del principio y otra del final.
    """
    s1, r1, s2, r2 = (texto_a_ms(t) for t in (sub_1, real_1, sub_2, real_2))

    if s2 <= s1 or r2 <= r1:
        raise ValueError("El segundo punto debe ir después del primero.")

    factor = (r2 - r1) / (s2 - s1)

    # Un factor fuera de este rango casi siempre es un error al escribir
    # los tiempos (ej. 25 fps vs 23.976 fps da apenas ~1.04).
    if not 0.5 <= factor <= 2.0:
        raise ValueError(
            "Los puntos dan un ajuste demasiado grande. Revisa los tiempos."
        )

    return AjusteLineal(factor=factor, desplazamiento_ms=r1 - s1 * factor)


def describir_ajuste(ajuste: AjusteLineal) -> str:
    """Explica el ajuste en palabras, para mostrarlo en la ventana."""
    if ajuste.sin_cambios:
        return "El subtítulo ya está sincronizado; no hay nada que mover."
    if ajuste.estira:
        porcentaje = (ajuste.factor - 1.0) * 100
        verbo = "estiran" if porcentaje > 0 else "encogen"
        return f"Los tiempos se {verbo} un {abs(porcentaje):.2f} % y se reubican."

    ms = round(ajuste.desplazamiento_ms)
    if ms > 0:
        return f"Hay que ATRASAR el subtítulo {ms_a_texto(ms)} (aparecerá más tarde)."
    return f"Hay que ADELANTAR el subtítulo {ms_a_texto(-ms)} (aparecerá antes)."


# ---------------------------------------------------------------------------
# 2. Aplicar el ajuste
# ---------------------------------------------------------------------------


def aplicar_ajuste(
    lineas: list[Linea], ajuste: AjusteLineal
) -> tuple[list[Linea], int, int]:
    """Aplica el ajuste a todas las líneas (RF-09).

    Devuelve (líneas_nuevas, recortadas, eliminadas):
      - Si una línea queda empezando antes del segundo 0, se recorta a 0.
      - Si una línea queda terminando antes del segundo 0, se elimina.
    """
    nuevas: list[Linea] = []
    recortadas = eliminadas = 0
    for linea in lineas:
        inicio = ajuste.aplicar(linea.inicio)
        fin = ajuste.aplicar(linea.fin)
        if fin <= 0:
            eliminadas += 1
            continue
        if inicio < 0:
            inicio = 0
            recortadas += 1
        nuevas.append(Linea(inicio, fin, linea.texto))
    return nuevas, recortadas, eliminadas


@dataclass(frozen=True)
class ResultadoSincronizacion:
    """Resumen de la sincronización, para mostrarlo en la ventana."""

    ruta_salida: Path
    lineas_guardadas: int
    lineas_recortadas: int
    lineas_eliminadas: int


def ruta_sincronizada_disponible(ruta_entrada: Path) -> Path:
    """Dónde guardar el subtítulo sincronizado sin pisar nada (RNF-02).

    "Serie.srt"      -> "Serie.sync.srt"
    "Serie.ass"      -> "Serie.sync.srt"
    "Serie.sync.srt" -> "Serie.sync (2).srt"  (no "Serie.sync.sync.srt")
    """
    ruta_entrada = Path(ruta_entrada)
    nombre = ruta_entrada.stem
    if nombre.lower().endswith(".sync"):
        nombre = nombre[: -len(".sync")]
    return ruta_sin_conflicto(ruta_entrada.with_name(f"{nombre}.sync.srt"))


def sincronizar_archivo(
    ruta_entrada: Path,
    ajuste: AjusteLineal,
    ruta_salida: Path | None = None,
    fps: float | None = None,
) -> ResultadoSincronizacion:
    """Lee un subtítulo (cualquier formato), lo sincroniza y lo guarda como SRT."""
    lectura = leer_lineas(ruta_entrada, fps)
    nuevas, recortadas, eliminadas = aplicar_ajuste(lectura.lineas, ajuste)

    salida = Path(ruta_salida) if ruta_salida else ruta_sincronizada_disponible(ruta_entrada)
    guardar_srt(nuevas, salida, ruta_entrada)

    return ResultadoSincronizacion(
        ruta_salida=salida,
        lineas_guardadas=len(nuevas),
        lineas_recortadas=recortadas,
        lineas_eliminadas=eliminadas,
    )
