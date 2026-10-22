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

## Estructura del proyecto

```
SubtitulosMP4/
├── main.py                  # Punto de entrada: abre la ventana
├── submp4/
│   ├── nucleo/              # Lógica, sin interfaz (se puede probar sola)
│   │   ├── tiempo.py        # Convertir "00:01:23" ⇄ milisegundos
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
