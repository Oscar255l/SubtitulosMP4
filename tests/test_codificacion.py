from submp4.nucleo.codificacion import decodificar, leer_texto

TEXTO = "¿Qué año es? Mañana, señor."


def test_utf8():
    assert decodificar(TEXTO.encode("utf-8")) == (TEXTO, "utf-8-sig")


def test_utf8_con_bom():
    texto, _ = decodificar(b"\xef\xbb\xbf" + TEXTO.encode("utf-8"))
    assert texto == TEXTO  # El BOM no debe quedar al inicio.


def test_windows_1252():
    assert decodificar(TEXTO.encode("cp1252")) == (TEXTO, "cp1252")


def test_utf16():
    assert decodificar(TEXTO.encode("utf-16")) == (TEXTO, "utf-16")


def test_leer_texto_desde_archivo(tmp_path):
    archivo = tmp_path / "ejemplo.srt"
    archivo.write_bytes(TEXTO.encode("cp1252"))
    assert leer_texto(archivo)[0] == TEXTO
