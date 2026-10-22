import shutil
from pathlib import Path

import pytest

from submp4.nucleo.conversion import (
    ErrorConversion,
    Linea,
    aplanar_superposiciones,
    convertir_a_srt,
    es_estilo_de_efecto,
    generar_srt,
    ruta_srt_disponible,
    texto_ass_a_srt,
)

MUESTRAS = Path(__file__).parent / "muestras"


def _copiar_muestra(nombre: str, destino: Path) -> Path:
    """Copia una muestra a una carpeta temporal para no ensuciar el repo."""
    return Path(shutil.copy(MUESTRAS / nombre, destino))


def _bloques(ruta: Path) -> list[str]:
    """Devuelve los bloques de un SRT (número, tiempos y texto)."""
    return ruta.read_text(encoding="utf-8").strip().split("\n\n")


# ---------- Nombres de estilos ----------


@pytest.mark.parametrize(
    "nombre", ["Signs", "sign", "Song_Romaji", "Karaoke", "OP", "ED2", "OP-English", "Title", "TS"]
)
def test_estilos_de_efecto(nombre):
    assert es_estilo_de_efecto(nombre)


@pytest.mark.parametrize("nombre", ["Default", "Main", "Italics", "Top", "Dialogue", "Flashback", "Narrator"])
def test_estilos_de_dialogo(nombre):
    assert not es_estilo_de_efecto(nombre)


# ---------- Limpieza de texto ----------


@pytest.mark.parametrize(
    "ass, srt",
    [
        (r"{\an8}Hola", "Hola"),
        (r"{\fad(200,200)\c&H00FFFF&}Hola", "Hola"),
        (r"Hola\NMundo", "Hola\nMundo"),
        (r"Hola\nMundo", "Hola\nMundo"),
        (r"Hola\hMundo", "Hola Mundo"),
        (r"{\i1}Hola{\i0} mundo", "<i>Hola</i> mundo"),
        (r"{\b1}Hola{\b0}", "<b>Hola</b>"),
        (r"{\b700}Hola", "<b>Hola</b>"),
        (r"{\bord3\blur0.6\be1}Hola", "Hola"),  # No confundir con negrita
        (r"{\i1}Sin cerrar", "<i>Sin cerrar</i>"),
        (r"{\i1}{\i0}Hola", "Hola"),  # Etiquetas vacías fuera
        (r"  Hola  \N\N  ", "Hola"),  # Espacios y renglones vacíos fuera
        (r"{\i1}", ""),
    ],
)
def test_texto_ass_a_srt(ass, srt):
    assert texto_ass_a_srt(ass) == srt


def test_estilo_en_cursiva_envuelve_la_linea():
    assert texto_ass_a_srt("Recuerdo", italica=True) == "<i>Recuerdo</i>"


# ---------- Superposiciones ----------


def test_lineas_simultaneas_se_fusionan():
    resultado = aplanar_superposiciones([Linea(0, 2000, "- ¿Vienes?"), Linea(0, 2000, "- Sí.")])
    assert resultado == [Linea(0, 2000, "- ¿Vienes?\n- Sí.")]


def test_superposicion_parcial_se_divide_en_tramos():
    resultado = aplanar_superposiciones([Linea(0, 4000, "A"), Linea(2000, 6000, "B")])
    assert resultado == [Linea(0, 2000, "A"), Linea(2000, 4000, "A\nB"), Linea(4000, 6000, "B")]


def test_lineas_seguidas_no_cambian():
    lineas = [Linea(0, 1000, "A"), Linea(1000, 2000, "B"), Linea(3000, 4000, "C")]
    assert aplanar_superposiciones(lineas) == lineas


def test_duplicados_y_lineas_sin_duracion_se_descartan():
    resultado = aplanar_superposiciones(
        [Linea(0, 1000, "A"), Linea(0, 1000, "A"), Linea(500, 500, "X")]
    )
    assert resultado == [Linea(0, 1000, "A")]


def test_generar_srt():
    assert generar_srt([Linea(6000, 8500, "Hola")]) == "1\n00:00:06,000 --> 00:00:08,500\nHola\n"


# ---------- Rutas de salida ----------


def test_ruta_desde_ass(tmp_path):
    assert ruta_srt_disponible(tmp_path / "Serie.ass") == tmp_path / "Serie.srt"


def test_ruta_desde_srt_no_pisa_el_original(tmp_path):
    assert ruta_srt_disponible(tmp_path / "Serie.srt") == tmp_path / "Serie.convertido.srt"


def test_ruta_ocupada(tmp_path):
    (tmp_path / "Serie.srt").touch()
    assert ruta_srt_disponible(tmp_path / "Serie.ass") == tmp_path / "Serie (2).srt"


# ---------- Conversión completa de archivos ----------


def test_convertir_ass_quita_efectos(tmp_path):
    original = _copiar_muestra("ejemplo.ass", tmp_path)
    contenido_original = original.read_bytes()

    resultado = convertir_a_srt(original)

    assert resultado.formato_origen == "ass"
    assert resultado.lineas_leidas == 6
    assert resultado.efectos_quitados == 3  # Letrero, karaoke y dibujo
    assert _bloques(resultado.ruta_salida) == [
        "1\n00:00:06,000 --> 00:00:08,500\nHey, are you coming tonight?",
        "2\n00:00:09,000 --> 00:00:11,200\nI don't know yet.\nMaybe later.",
        "3\n00:00:12,000 --> 00:00:14,000\n<i>Come on, it'll be fun!</i>",
    ]
    assert original.read_bytes() == contenido_original  # El original no se toca


def test_convertir_srt_conserva_cursivas(tmp_path):
    resultado = convertir_a_srt(_copiar_muestra("ejemplo.srt", tmp_path))
    assert resultado.ruta_salida.name == "ejemplo.convertido.srt"
    assert "<i>Come on, it'll be fun!</i>" in resultado.ruta_salida.read_text(encoding="utf-8")


def test_convertir_srt_en_windows_1252_queda_en_utf8(tmp_path):
    entrada = tmp_path / "latino.srt"
    entrada.write_bytes("1\n00:00:01,000 --> 00:00:02,000\n¿Qué año es, señor?\n".encode("cp1252"))

    resultado = convertir_a_srt(entrada)

    assert resultado.codificacion_origen == "cp1252"
    assert "¿Qué año es, señor?" in resultado.ruta_salida.read_text(encoding="utf-8")


def test_convertir_vtt(tmp_path):
    entrada = tmp_path / "web.vtt"
    entrada.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:03.500\nHello there\n\n"
        "00:00:04.000 --> 00:00:05.000\n<i>General Kenobi</i>\n",
        encoding="utf-8",
    )
    bloques = _bloques(convertir_a_srt(entrada).ruta_salida)
    assert bloques[0] == "1\n00:00:01,000 --> 00:00:03,500\nHello there"
    assert len(bloques) == 2


def test_convertir_microdvd_con_fps(tmp_path):
    entrada = tmp_path / "viejo.sub"
    entrada.write_text("{0}{50}Hola|Mundo\n{75}{100}Chao\n", encoding="utf-8")

    resultado = convertir_a_srt(entrada, fps=25)

    assert _bloques(resultado.ruta_salida)[0] == "1\n00:00:00,000 --> 00:00:02,000\nHola\nMundo"


def test_convertir_microdvd_sin_fps_pide_los_fps(tmp_path):
    entrada = tmp_path / "viejo.sub"
    entrada.write_text("{0}{50}Hola\n", encoding="utf-8")
    with pytest.raises(ErrorConversion, match="FPS"):
        convertir_a_srt(entrada)


def test_archivo_que_no_existe(tmp_path):
    with pytest.raises(ErrorConversion, match="No existe"):
        convertir_a_srt(tmp_path / "fantasma.ass")


def test_formato_desconocido(tmp_path):
    entrada = tmp_path / "notas.docx"
    entrada.write_text("esto no es un subtítulo", encoding="utf-8")
    with pytest.raises(ErrorConversion, match="formato"):
        convertir_a_srt(entrada)
