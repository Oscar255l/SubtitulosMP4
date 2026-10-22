import pytest

from submp4.nucleo.tiempo import ms_a_texto, texto_a_ms, texto_con_signo_a_ms


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("83", 83_000),
        ("1:23", 83_000),
        ("00:01:23", 83_000),
        ("00:00:6", 6_000),
        ("00:01:23,500", 83_500),
        ("00:01:23.5", 83_500),
        ("1:00:00", 3_600_000),
        ("  00:00:10  ", 10_000),
    ],
)
def test_texto_a_ms_formatos_validos(texto, esperado):
    assert texto_a_ms(texto) == esperado


@pytest.mark.parametrize("texto", ["", "abc", "1:2:3:4", "00:75:00", "00:01:60", "-5"])
def test_texto_a_ms_rechaza_formatos_invalidos(texto):
    with pytest.raises(ValueError):
        texto_a_ms(texto)


@pytest.mark.parametrize(
    "texto, esperado",
    [("+2.5", 2_500), ("-1,5", -1_500), ("3", 3_000), ("-00:00:01", -1_000)],
)
def test_texto_con_signo(texto, esperado):
    assert texto_con_signo_a_ms(texto) == esperado


def test_ms_a_texto():
    assert ms_a_texto(83_500) == "00:01:23,500"
    assert ms_a_texto(-1_500) == "-00:00:01,500"
    assert ms_a_texto(0) == "00:00:00,000"
