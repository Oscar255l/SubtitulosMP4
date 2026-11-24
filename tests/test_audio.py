import json
import re
import shutil
import subprocess  # nosec B404 - solo para crear y medir videos de prueba
from pathlib import Path

import pytest

from submp4.nucleo.audio import (
    NIVELES,
    ErrorAudio,
    PistaAudio,
    analizar_audio,
    construir_comando,
    construir_filtro,
    elegir_pista,
    mejorar_audio,
    pistas_desde_ffprobe,
    probar_fragmento,
    ruta_audio_disponible,
)

MUESTRAS = Path(__file__).parent / "muestras"
HAY_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
necesita_ffmpeg = pytest.mark.skipif(not HAY_FFMPEG, reason="FFmpeg no está instalado")


# ---------- Filtros ----------


def test_filtro_5_1_realza_el_canal_central():
    filtro = construir_filtro(6, "Media")
    assert filtro.startswith("pan=stereo|FL<1.0*c2+0.5*c0+0.35*c4+0.15*c3|FR<1.0*c2+0.5*c1+0.35*c5")
    assert "dynaudnorm" in filtro and "alimiter" in filtro


def test_filtro_fuerte_quita_el_subwoofer():
    assert "c3" not in construir_filtro(6, "Fuerte").split(",")[0]


def test_filtro_7_1_usa_los_cuatro_envolventes():
    mezcla = construir_filtro(8, "Media").split(",")[0]
    assert "c4" in mezcla and "c6" in mezcla  # Izquierda
    assert "c5" in mezcla and "c7" in mezcla  # Derecha


def test_filtro_estereo_reduce_los_lados():
    assert construir_filtro(2, "Fuerte").startswith("stereotools=slev=0.4")


def test_filtro_mono_solo_nivela():
    assert construir_filtro(1, "Media").startswith("bass=")


def test_filtro_distribucion_rara_se_pasa_a_estereo():
    assert construir_filtro(4, "Media").startswith("aformat=channel_layouts=stereo")


def test_niveles_van_de_menos_a_mas():
    suave, media, fuerte = NIVELES["Suave"], NIVELES["Media"], NIVELES["Fuerte"]
    assert suave.frontales > media.frontales > fuerte.frontales
    assert suave.proporcion < media.proporcion < fuerte.proporcion


def test_nivel_desconocido():
    with pytest.raises(ErrorAudio, match="Intensidad"):
        construir_filtro(2, "Extrema")


# ---------- Pistas de audio ----------

_FFPROBE = {
    "streams": [
        {"codec_name": "ac3", "channels": 6, "tags": {"language": "spa", "title": "Latino"},
         "disposition": {"default": 1}},
        {"codec_name": "aac", "channels": 2, "tags": {"language": "eng", "handler_name": "SoundHandler"},
         "disposition": {"default": 0}},
        {"codec_name": "aac", "channels": 6, "tags": {"language": "eng"}, "disposition": {"default": 0}},
    ]
}


def test_pistas_desde_ffprobe():
    latino, ingles, ingles_51 = pistas_desde_ffprobe(_FFPROBE)
    assert latino == PistaAudio(0, "ac3", 6, "spa", "Latino", True)
    assert ingles.titulo == ""  # "SoundHandler" no dice nada: se ignora
    assert latino.descripcion() == "Pista 1 · Español · Latino · 5.1 · AC3"
    assert ingles.descripcion() == "Pista 2 · Inglés · Estéreo · AAC"
    assert ingles_51.es_envolvente and not ingles.es_envolvente


def test_nombre_original():
    _, ingles, _ = pistas_desde_ffprobe(_FFPROBE)
    assert ingles.nombre_original() == "Inglés · Original (Estéreo)"


def test_elegir_prefiere_ingles_con_mas_canales():
    assert elegir_pista(pistas_desde_ffprobe(_FFPROBE)) == 2


def test_elegir_sin_ingles_usa_la_activa():
    pistas = [PistaAudio(0, "aac", 2, "spa"), PistaAudio(1, "aac", 2, "por", por_defecto=True)]
    assert elegir_pista(pistas) == 1


def test_elegir_no_vuelve_a_mejorar_una_pista_mejorada():
    pistas = [
        PistaAudio(0, "aac", 2, "eng", "Inglés · Voces mejoradas (Media)", True),
        PistaAudio(1, "aac", 6, "eng", "Inglés · Original (5.1)"),
    ]
    assert elegir_pista(pistas) == 1


# ---------- Comando de FFmpeg ----------


def test_construir_comando(tmp_path):
    pistas = pistas_desde_ffprobe(_FFPROBE)
    comando = construir_comando(
        "ffmpeg", tmp_path / "v.mp4", pistas[2], "FILTRO", "Inglés · Voces mejoradas (Media)",
        tmp_path / "s.mp4", originales=pistas,
    )
    texto = " ".join(comando)
    assert "-n" in comando
    assert comando[-1] == f"file:{(tmp_path / 's.mp4').resolve()}"
    assert "-map 0:v? -map 0:a:2 -map 0:a -map 0:s?" in texto
    assert "-c copy -filter:a:0 FILTRO -c:a:0 aac" in texto
    assert "-disposition:a 0 -disposition:a:0 default" in texto
    assert "-metadata:s:a:1 handler_name=Latino" in texto
    assert "-metadata:s:a:2 handler_name=Inglés · Original (Estéreo)" in texto
    assert "-ss" not in comando


def test_construir_comando_fragmento_sin_originales(tmp_path):
    pista = PistaAudio(0, "aac", 2, "eng")
    comando = construir_comando(
        "ffmpeg", tmp_path / "v.mp4", pista, "F", "N", tmp_path / "s.mp4",
        conservar_originales=False, inicio_ms=90_500, duracion_s=120,
    )
    # -ss antes de -i (salto rápido) y -t después.
    assert comando.index("-ss") < comando.index("-i") < comando.index("-t")
    assert comando[comando.index("-ss") + 1] == "90.500"
    assert "0:a" not in comando


def test_ruta_audio(tmp_path):
    assert ruta_audio_disponible(tmp_path / "Peli.mp4") == tmp_path / "Peli.audio.mp4"
    assert ruta_audio_disponible(tmp_path / "Peli.mp4", prueba=True) == tmp_path / "Peli.audio-prueba.mp4"
    (tmp_path / "Peli.audio.mp4").touch()
    assert ruta_audio_disponible(tmp_path / "Peli.mp4") == tmp_path / "Peli.audio (2).mp4"


# ---------- Validaciones ----------


def test_video_que_no_es_mp4(tmp_path):
    video = tmp_path / "v.mkv"
    video.touch()
    with pytest.raises(ErrorAudio, match=".mp4"):
        mejorar_audio(video)


def test_inicio_de_fragmento_invalido(tmp_path):
    video = tmp_path / "v.mp4"
    video.touch()
    with pytest.raises(ErrorAudio, match="Tiempo no válido"):
        probar_fragmento(video, "la mitad")


# ---------- Con FFmpeg real ----------

# Una "película" de 14 s: voz suave (tono de 300 Hz) todo el tiempo y una
# "explosión" fuerte (ruido) de 8 a 11 s.
_VOZ = "0.04*sin(2*PI*300*t)"
_EXPLOSION = "if(between(t,8,11),0.5*(random({semilla})*2-1),0)"


def _crear_pelicula(ruta: Path, canales: int, segundos: int = 14) -> Path:
    if canales == 6:  # FL FR FC LFE BL BR: la voz solo en el centro
        expresiones = [_EXPLOSION.format(semilla=i) for i in range(6)]
        expresiones[2] = _VOZ
        distribucion = "5.1"
    else:  # Estéreo: voz en el centro y explosión distinta en cada lado
        expresiones = [f"{_VOZ}+{_EXPLOSION.format(semilla=i)}" for i in range(2)]
        distribucion = "stereo"
    # Las comillas evitan que FFmpeg tome las comas de las fórmulas como separadores.
    audio = f"aevalsrc=exprs='{'|'.join(expresiones)}':c={distribucion}:s=48000:d={segundos}"
    subprocess.run(  # nosec B603 B607 - comando fijo, solo en pruebas
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc=size=160x90:rate=24:duration={segundos}",
         "-f", "lavfi", "-i", audio,
         "-c:v", "mpeg4", "-c:a", "aac", "-b:a", "256k", "-metadata:s:a:0", "language=eng",
         f"file:{ruta}"],
        check=True,
    )
    return ruta


def _nivel_db(ruta: Path, desde: float, segundos: float, mezcla_normal: bool = False) -> float:
    """Volumen (RMS en dB) de la primera pista de audio en un tramo.

    mezcla_normal: pasa el audio a estéreo como lo haría un reproductor.
    """
    # aformat pasa a estéreo con la mezcla estándar de FFmpeg (sirve en versiones viejas y nuevas).
    filtro = ("aformat=channel_layouts=stereo," if mezcla_normal else "") + "astats=metadata=0:measure_perchannel=none"
    salida = subprocess.run(  # nosec B603 B607 - comando fijo, solo en pruebas
        ["ffmpeg", "-hide_banner", "-nostats", "-ss", str(desde), "-t", str(segundos),
         "-i", f"file:{ruta}", "-map", "0:a:0", "-af", filtro, "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    ).stderr
    return float(re.search(r"RMS level dB: (-?[\d.]+)", salida).group(1))


def _diferencia_explosion_voz(ruta: Path, mezcla_normal: bool = False) -> tuple[float, float]:
    """Devuelve (volumen de la voz, cuánto más fuerte suena la explosión)."""
    voz = _nivel_db(ruta, 2, 5, mezcla_normal)
    explosion = _nivel_db(ruta, 8.5, 2, mezcla_normal)
    return voz, explosion - voz


def _pistas(ruta: Path) -> list[dict]:
    salida = subprocess.run(  # nosec B603 B607 - comando fijo, solo en pruebas
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,channels:stream_tags=handler_name"
         ":stream_disposition=default:format=duration", "-of", "json", f"file:{ruta}"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return json.loads(salida.stdout)


@necesita_ffmpeg
def test_5_1_voces_mas_fuertes_y_explosion_mas_suave(tmp_path):
    video = _crear_pelicula(tmp_path / "Peli51.mp4", canales=6)
    voz_antes, diferencia_antes = _diferencia_explosion_voz(video, mezcla_normal=True)

    resultado = mejorar_audio(video, "Media")

    voz_despues, diferencia_despues = _diferencia_explosion_voz(resultado.ruta_salida)
    assert resultado.pista.es_envolvente
    assert diferencia_antes > 15  # Antes: la explosión tapaba la voz
    assert diferencia_despues < diferencia_antes - 10  # Ahora la diferencia es mucho menor
    assert voz_despues > voz_antes + 6  # Y la voz se oye más fuerte


@necesita_ffmpeg
def test_estereo_tambien_mejora(tmp_path):
    video = _crear_pelicula(tmp_path / "Peli20.mp4", canales=2)
    voz_antes, diferencia_antes = _diferencia_explosion_voz(video)

    resultado = mejorar_audio(video, "Media")

    voz_despues, diferencia_despues = _diferencia_explosion_voz(resultado.ruta_salida)
    assert diferencia_despues < diferencia_antes - 5
    assert voz_despues > voz_antes + 6


@necesita_ffmpeg
def test_pistas_del_video_nuevo(tmp_path):
    video = _crear_pelicula(tmp_path / "Peli.mp4", canales=6)
    original = video.read_bytes()

    resultado = mejorar_audio(video, "Suave")

    assert resultado.ruta_salida == tmp_path / "Peli.audio.mp4"
    assert video.read_bytes() == original  # El original no se toca
    pistas = _pistas(resultado.ruta_salida)["streams"]
    video_nuevo, mejorada, copia_original = pistas
    assert video_nuevo["codec_name"] == "mpeg4"  # Video copiado, no recodificado
    assert (mejorada["channels"], mejorada["disposition"]["default"]) == (2, 1)
    assert mejorada["tags"]["handler_name"] == "Inglés · Voces mejoradas (Suave)"
    assert (copia_original["channels"], copia_original["disposition"]["default"]) == (6, 0)
    assert copia_original["tags"]["handler_name"] == "Inglés · Original (5.1)"


@necesita_ffmpeg
def test_sin_conservar_originales(tmp_path):
    video = _crear_pelicula(tmp_path / "Peli.mp4", canales=2)
    resultado = mejorar_audio(video, conservar_originales=False)
    tipos = [p["codec_type"] for p in _pistas(resultado.ruta_salida)["streams"]]
    assert tipos == ["video", "audio"]


@necesita_ffmpeg
def test_fragmento_de_prueba(tmp_path):
    video = _crear_pelicula(tmp_path / "Peli.mp4", canales=2)
    avances = []

    resultado = probar_fragmento(video, "00:00:05", "Fuerte", al_progresar=avances.append)

    datos = _pistas(resultado.ruta_salida)
    assert resultado.ruta_salida.name == "Peli.audio-prueba.mp4"
    assert float(datos["format"]["duration"]) == pytest.approx(9, abs=0.6)  # De 5 s al final (14 s)
    assert [p["codec_type"] for p in datos["streams"]] == ["video", "audio", "audio"]  # Para comparar
    assert avances and avances[-1] == 1.0


@necesita_ffmpeg
def test_fragmento_despues_del_final(tmp_path):
    video = _crear_pelicula(tmp_path / "Peli.mp4", canales=2)
    with pytest.raises(ErrorAudio, match="El video dura"):
        probar_fragmento(video, "00:10:00")


@necesita_ffmpeg
def test_conserva_subtitulos(tmp_path):
    from submp4.nucleo.unir_video import PistaSubtitulo, unir_subtitulos

    video = _crear_pelicula(tmp_path / "Peli.mp4", canales=2)
    con_subtitulos = unir_subtitulos(video, [PistaSubtitulo(MUESTRAS / "ejemplo.srt", "eng")])

    resultado = mejorar_audio(con_subtitulos.ruta_salida)

    tipos = [p["codec_type"] for p in _pistas(resultado.ruta_salida)["streams"]]
    assert tipos == ["video", "audio", "audio", "subtitle"]


@necesita_ffmpeg
def test_video_sin_audio(tmp_path):
    video = tmp_path / "mudo.mp4"
    subprocess.run(  # nosec B603 B607 - comando fijo, solo en pruebas
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
         "testsrc=size=160x90:rate=24:duration=2", "-c:v", "mpeg4", f"file:{video}"],
        check=True,
    )
    with pytest.raises(ErrorAudio, match="no tiene pistas de audio"):
        analizar_audio(video)


@necesita_ffmpeg
def test_nombre_de_archivo_peligroso(tmp_path):
    video = _crear_pelicula(tmp_path / "-y & echo hackeado; #.mp4", canales=2, segundos=3)
    resultado = mejorar_audio(video)
    assert resultado.ruta_salida.name == "-y & echo hackeado; #.audio.mp4"


@necesita_ffmpeg
def test_no_toca_un_archivo_que_ya_existe(tmp_path):
    # FFmpeg con "-n" se niega a sobrescribir, pero termina con código de éxito:
    # la app debe avisar del error y no borrar ni cambiar el archivo existente.
    video = _crear_pelicula(tmp_path / "Peli.mp4", canales=2, segundos=3)
    existente = tmp_path / "importante.mp4"
    existente.write_text("no me borres", encoding="utf-8")

    with pytest.raises(ErrorAudio, match="Ya existe"):
        mejorar_audio(video, ruta_salida=existente)
    assert existente.read_text(encoding="utf-8") == "no me borres"


@necesita_ffmpeg
def test_video_danado(tmp_path):
    video = tmp_path / "danado.mp4"
    video.write_text("esto no es un video", encoding="utf-8")
    with pytest.raises(ErrorAudio, match="No se pudo leer el video"):
        mejorar_audio(video)
    assert not (tmp_path / "danado.audio.mp4").exists()
