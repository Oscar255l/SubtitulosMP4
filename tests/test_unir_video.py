from submp4.nucleo.conversion import es_formato_soportado
from submp4.nucleo.unir_video import ruta_salida_disponible


def test_ruta_salida_nueva(tmp_path):
    video = tmp_path / "Pelicula.mp4"
    assert ruta_salida_disponible(video) == tmp_path / "Pelicula.subs.mp4"


def test_ruta_salida_no_sobrescribe(tmp_path):
    video = tmp_path / "Pelicula.mp4"
    (tmp_path / "Pelicula.subs.mp4").touch()
    (tmp_path / "Pelicula.subs (2).mp4").touch()
    assert ruta_salida_disponible(video) == tmp_path / "Pelicula.subs (3).mp4"


def test_formatos_soportados():
    assert es_formato_soportado("serie.ASS")
    assert es_formato_soportado("serie.vtt")
    assert not es_formato_soportado("serie.docx")
