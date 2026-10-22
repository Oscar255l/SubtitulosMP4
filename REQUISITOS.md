# Requisitos — SubtitulosMP4

Documento de requisitos de la aplicación. Recoge las decisiones tomadas antes de
escribir código, para que el proyecto tenga un sustento claro.

## 1. Contexto

Tengo series y películas descargadas en **MP4** que quiero ver en inglés. Los
subtítulos que descargo vienen en formatos distintos (SRT, ASS, VTT…) y muchas
veces no están sincronizados con el video. Necesito una herramienta de
escritorio que:

1. Convierta cualquier subtítulo a **SRT**.
2. Lo **sincronice** con el video.
3. Lo **una al MP4** como pista que se puede activar y desactivar (subtítulo
   "suave", no quemado en la imagen).

## 2. Decisiones tomadas

| Tema | Decisión | Motivo |
|---|---|---|
| Plataforma | App de escritorio (Windows) | Los videos pesan varios GB; subirlos a una web no tiene sentido |
| Lenguaje | Python 3.11+ | Fácil de aprender, buenas librerías para subtítulos |
| Interfaz | Ventana gráfica desde el inicio, con CustomTkinter | Moderna y sencilla de programar |
| Formato de video | MP4 | Es el formato de toda mi colección |
| Formato de subtítulo final | SRT (dentro del MP4 como `mov_text`) | Es lo que soporta MP4 |
| Motor de video | FFmpeg | Une pistas sin recodificar, en segundos |
| Librería de subtítulos | pysubs2 | Lee y escribe muchos formatos |
| Archivo de salida | Siempre un archivo nuevo. Convertir y Sincronizar preguntan dónde guardar; Unir guarda junto al video | El original nunca se toca y yo decido dónde quedan los subtítulos |
| Efectos de ASS | Se quitan automáticamente | Letreros y karaoke ensucian el SRT |
| Repositorio | GitHub público | Portafolio y sustento de trabajos |

## 3. Requisitos funcionales

### Conversión (fase 1)

- **RF-01** Leer subtítulos en SRT, ASS, SSA, WebVTT (`.vtt`), MicroDVD (`.sub`),
  MPL2 y TMP, y convertirlos a SRT.
- **RF-02** Detectar la codificación del archivo (UTF-8, UTF-16, Windows-1252,
  Latin-1) y guardar siempre en **UTF-8**, para que la ñ y las tildes se vean bien.
- **RF-03** Al convertir desde ASS/SSA:
  - Eliminar etiquetas de estilo (`{\an8}`, `{\fad(...)}`, `{\c&H...&}`, etc.).
  - Convertir `{\i1}` y `{\b1}` en `<i>` y `<b>`.
  - Convertir `\N` y `\n` en saltos de línea reales.
  - Descartar dibujos vectoriales (`{\p1} ...`).
  - **Quitar automáticamente** letreros, karaoke y efectos. Una línea se
    considera efecto si:
    - su estilo se llama Sign, Song, Kara, Lyric, Title, Typeset, Insert,
      OP, ED, TS o FX (ej. `Signs`, `OP_Romaji`, `ED2`);
    - es un dibujo, tiene karaoke (`\k`), movimiento (`\move`), recortes
      (`\clip`), animación (`\t`), rotación (`\frz`) o cizallamiento (`\fax`);
    - tiene `\pos` junto con tipografía (fuente, tamaño, color, borde);
    - tiene algo en el campo *Effect* del ASS.
    Un diálogo con solo `{\an8}` o `{\pos(...)}` se conserva.
  - Fusionar los diálogos que se superponen: el tramo compartido muestra
    ambos textos, porque el MP4 no puede mostrar dos subtítulos a la vez.
- **RF-04** Para formatos basados en cuadros (MicroDVD), pedir o detectar los
  FPS del video.

### Sincronización (fase 2)

- **RF-05** Desplazar todo el subtítulo una cantidad de segundos, hacia adelante
  o hacia atrás (ej. `+2.5`, `-1,5`).
- **RF-06** Sincronizar por **un punto**: "el subtítulo empieza en 00:00:06 y
  el diálogo empieza en 00:01:23" → la app calcula el desplazamiento.
- **RF-07** Sincronizar por **dos puntos** (inicio y final) para corregir
  subtítulos que se van desfasando con el tiempo (diferencia de FPS).
- **RF-08** Aceptar tiempos como `HH:MM:SS`, `MM:SS`, segundos sueltos y con
  milisegundos (`00:01:23,500`).
- **RF-09** Las líneas que queden con tiempo negativo se recortan a 0 o se
  eliminan si terminan antes de 0.
- **RF-09a** Se puede sincronizar cualquier formato soportado; el resultado se
  guarda siempre como SRT limpio en `Nombre.sync.srt`.
- **RF-09b** Al elegir el archivo, la app muestra la primera y la última línea
  con sus tiempos y llena los campos "en el subtítulo"; el usuario solo escribe
  cuándo se dicen en el video. Hay vista previa antes de aplicar.

### Unión al video (fase 3)

- **RF-10** Unir uno o varios SRT a un MP4 sin recodificar el video ni el audio.
- **RF-11** Asignar idioma a cada pista (ej. inglés, español) y elegir cuál
  queda activa por defecto.
- **RF-12** Guardar como `Nombre.subs.mp4` junto al original; si ya existe,
  usar `Nombre.subs (2).mp4`, etc. Nunca sobrescribir.
- **RF-13** Mostrar el progreso y un mensaje claro si FFmpeg falla. Si falla,
  se borra el archivo a medio hacer.
- **RF-13a** Antes de unir, cada subtítulo pasa por la misma limpieza de la
  conversión (UTF-8, sin efectos, sin superposiciones), así se puede unir
  directamente un ASS o un SRT en Windows-1252.
- **RF-13b** Opción para conservar los subtítulos que el video ya traía.
  Las pistas nuevas quedan primero.
- **RF-13c** La unión corre en segundo plano: la ventana no se congela y no
  se puede cerrar a mitad de una unión.

### Interfaz (crece en cada fase)

- **RF-14** Ventana con tres pestañas: *Convertir*, *Sincronizar* y *Unir al video*.
- **RF-15** Seleccionar archivos con un botón "Buscar…".
- **RF-15a** Convertir y Sincronizar abren la ventana "Guardar como" de Windows,
  con el nombre sugerido (`Serie.srt`, `Serie.sync.srt`) y la carpeta del
  archivo original. Si se cancela, no se guarda nada. Unir al video guarda
  automáticamente en la carpeta del video.
- **RF-16** Avisar al abrir la app si FFmpeg no está instalado y explicar cómo
  instalarlo.
- **RF-17** Arrastrar y soltar archivos sobre cualquier campo de archivo
  (librería `tkinterdnd2`). Si se suelta un archivo de otro tipo, la app avisa.
  Es opcional: si la librería no carga, se sigue usando «Buscar…».

### Subtítulo bilingüe (fase 4)

- **RF-18** Al unir dos subtítulos, opción para agregar una tercera pista
  bilingüe: el subtítulo 1 arriba (ej. inglés) y el subtítulo 2 en cursiva
  debajo (ej. español). Se llama, por ejemplo, «Inglés + Español».
- **RF-19** Como los dos subtítulos casi nunca tienen los mismos tiempos, cada
  línea de la traducción se pega a la línea principal con la que más tiempo
  comparte en pantalla y se muestra durante toda esa línea (sin parpadeos).
  Las líneas de la traducción sin pareja se muestran solas.
- **RF-20** La pista bilingüe se puede elegir como la activa al abrir el video.

## 4. Requisitos no funcionales

- **RNF-01** Funciona en Windows 10/11 con 8 GB de RAM, sin conexión a internet.
- **RNF-02** El archivo original (video o subtítulo) nunca se modifica.
- **RNF-03 Seguridad:**
  - FFmpeg se ejecuta con `subprocess` pasando una **lista de argumentos**,
    nunca con `shell=True` (evita inyección de comandos por nombres de archivo).
  - Se validan las rutas antes de usarlas, y se pasan a FFmpeg absolutas y con
    el prefijo `file:`, para que un archivo llamado `-y.mp4` no se tome como
    una opción ni uno llamado `http:algo` como una dirección de internet.
  - FFmpeg se llama con `-n`, así nunca sobrescribe un archivo.
  - Hay pruebas automáticas con nombres de archivo maliciosos.
- **RNF-04** El núcleo (lógica) está separado de la interfaz, para poder
  probarlo sin abrir ventanas.
- **RNF-05** Pruebas automáticas con `pytest` para la lógica del núcleo,
  incluidas pruebas con FFmpeg real sobre un video generado.
- **RNF-06** Integración continua en GitHub Actions: instala FFmpeg, corre las
  pruebas y hace análisis SAST con Bandit en cada push.
- **RNF-07** Código comentado en español.
- **RNF-08** Licencia MIT.
- **RNF-09** El repositorio no incluye videos ni subtítulos con derechos de autor;
  las muestras de prueba son creadas por mí.

## 5. Fuera de alcance (por ahora)

- Extraer pistas de subtítulos que ya trae un MP4.
- Soporte para MKV y otros contenedores.
- Versión para celular.

## 6. Fases

| Fase | Contenido | Estado |
|---|---|---|
| 0 | Estructura, requisitos, ventana esqueleto, utilidades de tiempo y codificación | ✅ Hecho |
| 1 | Conversión a SRT con limpieza de ASS (RF-01 a RF-04) | ✅ Hecho |
| 2 | Sincronización (RF-05 a RF-09) | ✅ Hecho |
| 3 | Unión al MP4 con FFmpeg (RF-10 a RF-13) | ✅ Hecho |
| 4 | Pista bilingüe y arrastrar y soltar (RF-17 a RF-20) | ✅ Hecho |
