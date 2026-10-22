import json
import shutil
import subprocess  # nosec B404 - solo para crear videos de prueba
from pathlib import Path

import pytest

from submp4.nucleo.conversion import es_formato_soportado
from submp4.nucleo.unir_video import (
    ErrorUnion,
    PistaSubtitulo,
    construir_comando,
    fraccion_de_progreso,
    ruta_salida_disponible,
    unir_subtitulos,
)

MUESTRAS = Path(__file__).parent / "muestras"
HAY_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
necesita_ffmpeg = pytest.mark.skipif(not HAY_FFMPEG, reason="FFmpeg no está instalado")


# ---------- Rutas ----------


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


# ---------- Comando de FFmpeg ----------


def test_construir_comando(tmp_path):
    comando = construir_comando(
        "ffmpeg",
        tmp_path / "video.mp4",
        [(tmp_path / "en.srt", "eng", "Inglés"), (tmp_path / "es.srt", "spa", "Español")],
        tmp_path / "salida.mp4",
        por_defecto=1,
    )
    texto = " ".join(comando)

    assert comando[0] == "ffmpeg"
    assert "-n" in comando  # Nunca sobrescribir
    # Todas las rutas van absolutas y con "file:" (seguridad).
    assert f"file:{(tmp_path / 'video.mp4').resolve()}" in comando
    assert comando[-1] == f"file:{(tmp_path / 'salida.mp4').resolve()}"
    # Subtítulos nuevos primero, luego los que ya traía el video.
    assert "-map 1:0 -map 2:0 -map 0:s?" in texto
    assert "-c copy -c:s mov_text" in texto
    assert "-metadata:s:s:0 language=eng" in texto
    assert "-metadata:s:s:1 handler_name=Español" in texto
    assert "-disposition:s 0 -disposition:s:1 default" in texto


def test_construir_comando_sin_existentes_ni_defecto(tmp_path):
    comando = construir_comando(
        "ffmpeg", tmp_path / "v.mp4", [(tmp_path / "a.srt", "eng", "Inglés")],
        tmp_path / "s.mp4", por_defecto=None, conservar_existentes=False,
    )
    assert "0:s?" not in comando
    assert "default" not in comando


# ---------- Progreso ----------


@pytest.mark.parametrize(
    "linea, esperado",
    [
        ("out_time_us=5000000", 0.5),
        ("out_time_ms=10000000", 1.0),  # FFmpeg viejo: "ms" en realidad son µs
        ("out_time_us=20000000", 1.0),  # Nunca más de 1
        ("progress=end", 1.0),
        ("frame=120", None),
        ("out_time_us=N/A", None),
    ],
)
def test_fraccion_de_progreso(linea, esperado):
    assert fraccion_de_progreso(linea, duracion=10.0) == esperado


def test_progreso_sin_duracion():
    assert fraccion_de_progreso("out_time_us=5000000", duracion=None) is None


# ---------- Validaciones ----------


def test_video_que_no_existe(tmp_path):
    with pytest.raises(ErrorUnion, match="No existe"):
        unir_subtitulos(tmp_path / "nada.mp4", [PistaSubtitulo(MUESTRAS / "ejemplo.srt")])


def test_video_que_no_es_mp4(tmp_path):
    video = tmp_path / "video.mkv"
    video.touch()
    with pytest.raises(ErrorUnion, match=".mp4"):
        unir_subtitulos(video, [PistaSubtitulo(MUESTRAS / "ejemplo.srt")])


def test_sin_subtitulos(tmp_path):
    video = tmp_path / "video.mp4"
    video.touch()
    with pytest.raises(ErrorUnion, match="al menos un"):
        unir_subtitulos(video, [])


def test_idioma_invalido(tmp_path):
    video = tmp_path / "video.mp4"
    video.touch()
    with pytest.raises(ErrorUnion, match="idioma"):
        unir_subtitulos(video, [PistaSubtitulo(MUESTRAS / "ejemplo.srt", idioma="eng; rm")])


# ---------- Con FFmpeg real ----------


def _crear_video(ruta: Path, segundos: int = 15) -> Path:
    """Crea un video MP4 de prueba (barras de color y un tono)."""
    subprocess.run(  # nosec B603 B607 - comando fijo, solo en pruebas
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc=size=160x90:rate=24:duration={segundos}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={segundos}",
         "-c:v", "mpeg4", "-c:a", "aac", "-shortest", f"file:{ruta}"],
        check=True,
    )
    return ruta


def _pistas_de_subtitulos(ruta: Path) -> list[dict]:
    salida = subprocess.run(  # nosec B603 B607 - comando fijo, solo en pruebas
        ["ffprobe", "-v", "error", "-select_streams", "s",
         "-show_entries", "stream=codec_name:stream_tags=language,handler_name"
         ":stream_disposition=default", "-of", "json", f"file:{ruta}"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(salida.stdout)["streams"]


@necesita_ffmpeg
def test_unir_dos_pistas(tmp_path):
    video = _crear_video(tmp_path / "Pelicula.mp4")
    original = video.read_bytes()
    espanol = tmp_path / "es.srt"
    espanol.write_text("1\n00:00:01,000 --> 00:00:03,000\n¿Vienes esta noche?\n", encoding="utf-8")
    avances = []

    resultado = unir_subtitulos(
        video,
        [PistaSubtitulo(MUESTRAS / "ejemplo.srt", "eng"), PistaSubtitulo(espanol, "spa")],
        por_defecto=1,
        al_progresar=avances.append,
    )

    assert resultado.ruta_salida == tmp_path / "Pelicula.subs.mp4"
    assert video.read_bytes() == original  # El original no se toca
    pistas = _pistas_de_subtitulos(resultado.ruta_salida)
    assert [p["codec_name"] for p in pistas] == ["mov_text", "mov_text"]
    assert [p["tags"]["language"] for p in pistas] == ["eng", "spa"]
    assert [p["tags"]["handler_name"] for p in pistas] == ["Inglés", "Español"]
    assert [p["disposition"]["default"] for p in pistas] == [0, 1]
    assert avances and avances[-1] == 1.0


@necesita_ffmpeg
def test_conserva_subtitulos_existentes(tmp_path):
    video = _crear_video(tmp_path / "Serie.mp4")
    primera = unir_subtitulos(video, [PistaSubtitulo(MUESTRAS / "ejemplo.srt", "eng")])
    segunda = unir_subtitulos(primera.ruta_salida, [PistaSubtitulo(MUESTRAS / "ejemplo.ass", "spa")])

    pistas = _pistas_de_subtitulos(segunda.ruta_salida)
    assert [p["tags"]["language"] for p in pistas] == ["spa", "eng"]  # Nueva primero
    assert [p["disposition"]["default"] for p in pistas] == [1, 0]


@necesita_ffmpeg
def test_acepta_ass_y_codificacion_windows(tmp_path):
    video = _crear_video(tmp_path / "Serie.mp4")
    latino = tmp_path / "latino.srt"
    latino.write_bytes("1\n00:00:01,000 --> 00:00:02,000\n¿Qué año es, señor?\n".encode("cp1252"))

    resultado = unir_subtitulos(
        video, [PistaSubtitulo(MUESTRAS / "ejemplo.ass", "eng"), PistaSubtitulo(latino, "spa")]
    )
    assert len(_pistas_de_subtitulos(resultado.ruta_salida)) == 2


@necesita_ffmpeg
def test_nombres_de_archivo_peligrosos(tmp_path):
    # Nombres que intentan parecer opciones o comandos: deben tratarse como archivos.
    video = _crear_video(tmp_path / "-y.mp4")
    subtitulo = Path(shutil.copy(MUESTRAS / "ejemplo.srt", tmp_path / 'a"; echo hackeado #.srt'))

    resultado = unir_subtitulos(video, [PistaSubtitulo(subtitulo, "eng")])

    assert resultado.ruta_salida.name == "-y.subs.mp4"
    assert len(_pistas_de_subtitulos(resultado.ruta_salida)) == 1


@necesita_ffmpeg
def test_video_danado_no_deja_archivo_a_medias(tmp_path):
    video = tmp_path / "danado.mp4"
    video.write_text("esto no es un video", encoding="utf-8")

    with pytest.raises(ErrorUnion, match="FFmpeg no pudo"):
        unir_subtitulos(video, [PistaSubtitulo(MUESTRAS / "ejemplo.srt", "eng")])
    assert not (tmp_path / "danado.subs.mp4").exists()
