import pytest

from submp4.nucleo.sincronizacion import ajuste_por_dos_puntos, desplazamiento_por_punto


def test_desplazamiento_por_punto_atrasar():
    # El ejemplo del proyecto: empieza en 6 s, hablan en 1:23 -> +77 s.
    assert desplazamiento_por_punto("00:00:06", "00:01:23") == 77_000


def test_desplazamiento_por_punto_adelantar():
    assert desplazamiento_por_punto("00:00:10", "00:00:07,500") == -2_500


def test_dos_puntos_sin_estiramiento_es_un_desplazamiento():
    ajuste = ajuste_por_dos_puntos("00:00:10", "00:00:15", "00:40:00", "00:40:05")
    assert ajuste.factor == pytest.approx(1.0)
    assert ajuste.aplicar(20_000) == 25_000


def test_dos_puntos_corrige_diferencia_de_fps():
    # Subtítulo hecho para 25 fps en un video de 23.976 fps:
    # los tiempos reales son 25/23.976 veces más largos.
    factor_real = 25 / 23.976
    ajuste = ajuste_por_dos_puntos(
        "00:01:00", f"{60 * factor_real:.3f}", "00:40:00", f"{2400 * factor_real:.3f}"
    )
    assert ajuste.factor == pytest.approx(factor_real, rel=1e-4)
    # Un punto intermedio también queda bien (tolerancia de 5 ms).
    assert abs(ajuste.aplicar(1_200_000) - 1_200_000 * factor_real) < 5


def test_dos_puntos_rechaza_orden_invertido():
    with pytest.raises(ValueError):
        ajuste_por_dos_puntos("00:40:00", "00:40:05", "00:00:10", "00:00:15")


def test_dos_puntos_rechaza_ajuste_absurdo():
    with pytest.raises(ValueError):
        ajuste_por_dos_puntos("00:00:10", "00:00:10", "00:00:20", "00:10:00")
