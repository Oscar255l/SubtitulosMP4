"""Ejecutar FFmpeg y ffprobe de forma segura (lo usan Unir al video y Mejorar audio).

SEGURIDAD (RNF-03):
    - FFmpeg se ejecuta con subprocess pasando una LISTA de argumentos y sin
      shell=True: un nombre de archivo como 'pelicula & del *.mp4' nunca se
      interpreta como un comando.
    - Las rutas se pasan absolutas y con el prefijo "file:", para que FFmpeg
      no confunda un archivo llamado "-y.mp4" con una opción, ni uno llamado
      "http:algo" con una dirección de internet.
    - Los comandos usan "-n": FFmpeg nunca sobrescribe un archivo existente.
"""

import json
import re
import shutil
import subprocess  # nosec B404 - se usa de forma segura (ver arriba)
import tempfile
from collections.abc import Callable
from pathlib import Path

# En Windows, evita que se abra una ventana negra de consola al llamar a FFmpeg.
SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ErrorFFmpeg(Exception):
    """FFmpeg terminó con error. `detalle` tiene sus últimas líneas de error."""

    def __init__(self, detalle: str):
        super().__init__(detalle)
        self.detalle = detalle


def buscar_ffmpeg() -> str | None:
    """Devuelve la ruta de FFmpeg si está instalado, o None si no (RF-16)."""
    return shutil.which("ffmpeg")


def buscar_ffprobe() -> str | None:
    """ffprobe viene junto con FFmpeg; sirve para leer información del video."""
    return shutil.which("ffprobe")


def como_archivo(ruta: Path) -> str:
    """Ruta absoluta con prefijo "file:" (ver SEGURIDAD arriba)."""
    return f"file:{Path(ruta).resolve()}"


def consultar_ffprobe(ruta: Path, argumentos: list[str]) -> dict | None:
    """Ejecuta ffprobe con salida JSON y devuelve el resultado, o None si falla."""
    ffprobe = buscar_ffprobe()
    if not ffprobe:
        return None
    try:
        salida = subprocess.run(  # nosec B603 - lista de argumentos, sin shell
            [ffprobe, "-v", "error", *argumentos, "-of", "json", como_archivo(ruta)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, check=False, creationflags=SIN_VENTANA,
        )
        if salida.returncode != 0:
            return None
        return json.loads(salida.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def duracion_video(ruta_video: Path) -> float | None:
    """Duración del video en segundos, o None si no se puede saber."""
    datos = consultar_ffprobe(ruta_video, ["-show_entries", "format=duration"])
    try:
        return float(datos["format"]["duration"])
    except (TypeError, KeyError, ValueError):
        return None


_TIEMPO_PROCESADO = re.compile(r"^out_time_(?:us|ms)=(\d+)$")


def fraccion_de_progreso(linea: str, duracion: float | None) -> float | None:
    """Lee una línea de "-progress" y devuelve el avance entre 0 y 1.

    Devuelve None si la línea no dice nada del avance.
    """
    linea = linea.strip()
    if linea == "progress=end":
        return 1.0
    coincidencia = _TIEMPO_PROCESADO.match(linea)
    if not coincidencia or not duracion:
        return None
    segundos = int(coincidencia.group(1)) / 1_000_000  # Viene en microsegundos
    return max(0.0, min(1.0, segundos / duracion))


def ejecutar_ffmpeg(
    comando: list[str],
    ruta_salida: Path,
    duracion: float | None,
    al_progresar: Callable[[float], None] | None = None,
) -> None:
    """Ejecuta FFmpeg informando el avance (el comando debe incluir "-progress pipe:1").

    - Nunca toca un archivo que ya existía: si la salida existe, no ejecuta nada.
      (Ojo: con "-n", FFmpeg se niega a sobrescribir pero termina con código
      de ÉXITO, por eso hay que revisarlo aquí.)
    - Si FFmpeg falla, borra el archivo a medio hacer (lo creó él, nunca es
      el original) y lanza ErrorFFmpeg con las últimas líneas del error.
    - Al terminar, comprueba que el archivo de salida realmente se creó.
    """
    ruta_salida = Path(ruta_salida)
    if ruta_salida.exists():
        raise ErrorFFmpeg(f"Ya existe un archivo con ese nombre: {ruta_salida.name}")

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as errores:
        proceso = subprocess.Popen(  # nosec B603 - lista de argumentos, sin shell
            comando,
            stdout=subprocess.PIPE,
            stderr=errores,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=SIN_VENTANA,
        )
        try:
            for linea in proceso.stdout:
                fraccion = fraccion_de_progreso(linea, duracion)
                if fraccion is not None and al_progresar:
                    al_progresar(fraccion)
            codigo = proceso.wait()
        except BaseException:
            # Si algo falla aquí (incluso Ctrl+C), no dejar FFmpeg trabajando solo.
            proceso.kill()
            proceso.wait()
            if ruta_salida.exists():
                ruta_salida.unlink()
            raise

        creado = ruta_salida.exists() and ruta_salida.stat().st_size > 0
        if codigo != 0 or not creado:
            if ruta_salida.exists():
                ruta_salida.unlink()
            errores.seek(0)
            ultimas = "\n".join(errores.read().strip().splitlines()[-4:])
            raise ErrorFFmpeg(ultimas or "(sin detalle)")
