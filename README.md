# SubtitulosMP4

![CI](https://github.com/Oscar255l/SubtitulosMP4/actions/workflows/ci.yml/badge.svg)

Aplicación de escritorio para preparar subtítulos de series y películas en MP4:

- 🔄 **Convierte** subtítulos de cualquier formato (ASS, SSA, VTT, SUB…) a **SRT**,
  limpiando etiquetas y efectos.
- ⏱️ **Sincroniza** subtítulos: por segundos, por un punto ("empieza en 00:00:06
  pero hablan en 00:01:23") o por dos puntos para corregir desfases.
- 🎬 **Une** el subtítulo al MP4 como pista que se activa y desactiva desde el
  reproductor, sin recodificar el video.

> Proyecto personal en desarrollo. Ver el avance en [REQUISITOS.md](REQUISITOS.md).

## Requisitos

- Windows 10/11
- [Python 3.11 o superior](https://www.python.org/downloads/) (marca *"Add Python to PATH"* al instalar)
- [FFmpeg](https://ffmpeg.org/) (solo para unir subtítulos al video)

### Instalar FFmpeg

En PowerShell:

```powershell
winget install Gyan.FFmpeg
```

Cierra y vuelve a abrir la terminal, y comprueba con:

```bash
ffmpeg -version
```

## Instalación

Desde Git Bash, dentro de la carpeta del proyecto:

```bash
python -m venv .venv
source .venv/Scripts/activate      # En PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Uso

```bash
python main.py
```

Flujo típico:

1. **Convertir:** eliges el subtítulo descargado (ASS, VTT, SUB…) y se guarda
   como `Serie.srt` limpio.
2. **Sincronizar:** la app muestra la primera línea; escribes cuándo empiezan a
   hablar en el video y se guarda `Serie.sync.srt`.
3. **Unir al video:** eliges el MP4, uno o dos subtítulos (ej. inglés y español)
   y se crea `Serie.subs.mp4`. En VLC o MX Player activas o desactivas el
   subtítulo desde el menú.

Ningún paso modifica los archivos originales.

## Estructura del proyecto

```
SubtitulosMP4/
├── main.py                  # Punto de entrada: abre la ventana
├── submp4/
│   ├── nucleo/              # Lógica, sin interfaz (se puede probar sola)
│   │   ├── tiempo.py        # Convertir "00:01:23" ⇄ milisegundos
│   │   ├── rutas.py         # Nombres de salida sin pisar archivos
│   │   ├── codificacion.py  # Leer archivos con ñ y tildes sin errores
│   │   ├── conversion.py    # Pasar cualquier formato a SRT
│   │   ├── sincronizacion.py# Desplazar y ajustar tiempos
│   │   └── unir_video.py    # Llamar a FFmpeg para unir al MP4
│   └── interfaz/
│       └── ventana.py       # Ventana con CustomTkinter
├── tests/                   # Pruebas automáticas con pytest
│   └── muestras/            # Subtítulos de ejemplo creados para pruebas
├── .github/workflows/ci.yml # Pruebas + análisis de seguridad (Bandit)
├── REQUISITOS.md
└── requirements.txt
```

## Desarrollo

```bash
pip install -r requirements-dev.txt
pytest -v                 # pruebas
bandit -r submp4 -ll      # análisis de seguridad (SAST)
```

## Licencia

[MIT](LICENSE)
