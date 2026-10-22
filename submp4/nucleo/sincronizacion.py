"""Cálculos de sincronización de subtítulos (fase 2).

Ya funcionan los CÁLCULOS (cuánto mover y cuánto estirar).
Falta aplicarlos a un archivo real: eso se hace en la fase 2.
"""

from dataclasses import dataclass
from pathlib import Path

from submp4.nucleo.tiempo import texto_a_ms


def desplazamiento_por_punto(inicio_subtitulo: str, inicio_dialogo: str) -> int:
    """Calcula cuántos milisegundos hay que mover el subtítulo (RF-06).

    Ejemplo: el subtítulo empieza en "00:00:06" pero el diálogo empieza en
    "00:01:23" -> hay que atrasarlo 77 segundos -> devuelve 77000.
    Un resultado negativo significa que hay que adelantarlo.
    """
    return texto_a_ms(inicio_dialogo) - texto_a_ms(inicio_subtitulo)


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


def aplicar_a_archivo(ruta_entrada: Path, ruta_salida: Path, ajuste: AjusteLineal) -> None:
    """Aplica el ajuste a todas las líneas de un subtítulo y lo guarda.

    PENDIENTE (fase 2): usar pysubs2, recortar tiempos negativos (RF-09).
    """
    raise NotImplementedError("Disponible en la fase 2.")
