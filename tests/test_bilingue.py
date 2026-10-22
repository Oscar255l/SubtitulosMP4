from submp4.nucleo.bilingue import combinar_bilingue, en_cursiva
from submp4.nucleo.conversion import Linea


def test_en_cursiva_por_renglon_sin_duplicar():
    assert en_cursiva("Hola\n<i>Mundo</i>") == "<i>Hola</i>\n<i>Mundo</i>"


def test_mismos_tiempos():
    resultado = combinar_bilingue(
        [Linea(1000, 3000, "Are you coming?")], [Linea(1000, 3000, "¿Vienes?")]
    )
    assert resultado == [Linea(1000, 3000, "Are you coming?\n<i>¿Vienes?</i>")]


def test_tiempos_un_poco_distintos_no_parpadean():
    # La traducción empieza y termina un poco distinto: se usa el tiempo del inglés.
    resultado = combinar_bilingue(
        [Linea(1000, 3000, "Are you coming?")], [Linea(1150, 3200, "¿Vienes?")]
    )
    assert resultado == [Linea(1000, 3000, "Are you coming?\n<i>¿Vienes?</i>")]


def test_frase_partida_en_dos_en_espanol():
    resultado = combinar_bilingue(
        [Linea(0, 4000, "I don't know yet, maybe later.")],
        [Linea(0, 2000, "Aún no sé,"), Linea(2000, 4000, "quizás luego.")],
    )
    assert resultado == [
        Linea(0, 4000, "I don't know yet, maybe later.\n<i>Aún no sé,</i>\n<i>quizás luego.</i>")
    ]


def test_traduccion_va_a_la_linea_con_mas_coincidencia():
    resultado = combinar_bilingue(
        [Linea(0, 2000, "First"), Linea(2000, 6000, "Second")],
        [Linea(1500, 5000, "Segunda")],  # 500 ms con First, 3000 ms con Second
    )
    assert resultado == [Linea(0, 2000, "First"), Linea(2000, 6000, "Second\n<i>Segunda</i>")]


def test_traduccion_sin_pareja_se_muestra_sola():
    resultado = combinar_bilingue([Linea(0, 1000, "Hi")], [Linea(5000, 6000, "¡Cuidado!")])
    assert resultado == [Linea(0, 1000, "Hi"), Linea(5000, 6000, "<i>¡Cuidado!</i>")]


def test_linea_en_ingles_sin_traduccion_queda_igual():
    resultado = combinar_bilingue([Linea(0, 1000, "Hi"), Linea(2000, 3000, "Bye")], [])
    assert resultado == [Linea(0, 1000, "Hi"), Linea(2000, 3000, "Bye")]


def test_rendimiento_con_muchas_lineas():
    # Un capítulo largo: 3000 líneas por idioma debe ser instantáneo.
    ingles = [Linea(i * 2000, i * 2000 + 1500, f"Line {i}") for i in range(3000)]
    espanol = [Linea(i * 2000 + 100, i * 2000 + 1600, f"Línea {i}") for i in range(3000)]
    resultado = combinar_bilingue(ingles, espanol)
    assert len(resultado) == 3000
    assert resultado[1234].texto == "Line 1234\n<i>Línea 1234</i>"
