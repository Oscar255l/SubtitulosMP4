import shutil
from pathlib import Path

import pytest

from submp4.nucleo.conversion import Linea
from submp4.nucleo.sincronizacion import (
    AjusteLineal,
    ajuste_por_dos_puntos,
    ajuste_por_punto,
    ajuste_por_segundos,
    aplicar_ajuste,
    describir_ajuste,
    desplazamiento_por_punto,
    ruta_sincronizada_disponible,
    sincronizar_archivo,
)

MUESTRAS = Path(__file__).parent / "muestras"


def _bloques(ruta: Path) -> list[str]:
    return ruta.read_text(encoding="utf-8").strip().split("\n\n")


# ---------- Ajustes por segundos y por un punto ----------


@pytest.mark.parametrize("texto, ms", [("+2.5", 2500), ("-1,5", -1500), ("3", 3000)])
def test_ajuste_por_segundos(texto, ms):
    ajuste = ajuste_por_segundos(texto)
    assert ajuste.factor == 1.0
    assert ajuste.aplicar(10_000) == 10_000 + ms


def test_ajuste_por_punto():
    assert ajuste_por_punto("00:00:06", "00:01:23").aplicar(6_000) == 83_000


def test_ajuste_por_segundos_invalido():
    with pytest.raises(ValueError):
        ajuste_por_segundos("dos segundos")


# ---------- Descripción en palabras ----------


def test_describir_atrasar():
    assert "ATRASAR" in describir_ajuste(AjusteLineal(1.0, 77_000))
    assert "00:01:17,000" in describir_ajuste(AjusteLineal(1.0, 77_000))


def test_describir_adelantar():
    assert "ADELANTAR" in describir_ajuste(AjusteLineal(1.0, -2_500))


def test_describir_sin_cambios():
    ajuste = AjusteLineal(1.0, 0)
    assert ajuste.sin_cambios
    assert "ya está sincronizado" in describir_ajuste(ajuste)


def test_describir_estiramiento():
    assert "estiran un 4.27 %" in describir_ajuste(AjusteLineal(1.0427, 0))


# ---------- Tiempos negativos (RF-09) ----------


def test_aplicar_ajuste_recorta_y_elimina():
    lineas = [Linea(1_000, 3_000, "A"), Linea(4_000, 6_000, "B"), Linea(8_000, 9_000, "C")]
    nuevas, recortadas, eliminadas = aplicar_ajuste(lineas, AjusteLineal(1.0, -5_000))
    assert nuevas == [Linea(0, 1_000, "B"), Linea(3_000, 4_000, "C")]
    assert (recortadas, eliminadas) == (1, 1)


# ---------- Archivos ----------


def test_ruta_sincronizada(tmp_path):
    assert ruta_sincronizada_disponible(tmp_path / "Serie.srt") == tmp_path / "Serie.sync.srt"
    assert ruta_sincronizada_disponible(tmp_path / "Serie.ass") == tmp_path / "Serie.sync.srt"


def test_ruta_sincronizada_no_repite_sync(tmp_path):
    (tmp_path / "Serie.sync.srt").touch()
    assert (
        ruta_sincronizada_disponible(tmp_path / "Serie.sync.srt")
        == tmp_path / "Serie.sync (2).srt"
    )


def test_sincronizar_srt_por_punto(tmp_path):
    original = Path(shutil.copy(MUESTRAS / "ejemplo.srt", tmp_path))
    contenido_original = original.read_bytes()

    resultado = sincronizar_archivo(original, ajuste_por_punto("00:00:06", "00:01:23"))

    assert resultado.ruta_salida.name == "ejemplo.sync.srt"
    assert resultado.lineas_guardadas == 3
    assert _bloques(resultado.ruta_salida)[0] == (
        "1\n00:01:23,000 --> 00:01:25,500\nHey, are you coming tonight?"
    )
    assert original.read_bytes() == contenido_original  # El original no se toca


def test_sincronizar_ass_directo_quita_efectos(tmp_path):
    original = Path(shutil.copy(MUESTRAS / "ejemplo.ass", tmp_path))
    resultado = sincronizar_archivo(original, ajuste_por_segundos("+1"))
    bloques = _bloques(resultado.ruta_salida)
    assert len(bloques) == 3  # Solo los diálogos
    assert bloques[2] == "3\n00:00:13,000 --> 00:00:15,000\n<i>Come on, it'll be fun!</i>"


def test_sincronizar_por_dos_puntos(tmp_path):
    original = Path(shutil.copy(MUESTRAS / "ejemplo.srt", tmp_path))
    # Primera línea: 6 s -> 10 s. Última línea: 12 s -> 22 s. Factor 2/1 → recta y = 2x - 2.
    ajuste = ajuste_por_dos_puntos("00:00:06", "00:00:10", "00:00:12", "00:00:22")
    bloques = _bloques(sincronizar_archivo(original, ajuste).ruta_salida)
    assert bloques[0].splitlines()[1] == "00:00:10,000 --> 00:00:15,000"
    assert bloques[2].splitlines()[1] == "00:00:22,000 --> 00:00:26,000"


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
