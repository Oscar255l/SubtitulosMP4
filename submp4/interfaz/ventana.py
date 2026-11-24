"""Ventana principal de la app, hecha con CustomTkinter (RF-14 a RF-17, RF-25).

Pestañas: Convertir (fase 1), Sincronizar (fase 2), Unir al video (fase 3,
con la pista bilingüe de la fase 4) y Mejorar audio (fase 5).
"""

import queue
import re
import threading
import tkinter
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

# Arrastrar y soltar (RF-17) es OPCIONAL: si la librería no está instalada
# o no carga, la app funciona igual con el botón "Buscar…".
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:  # pragma: no cover - depende de la instalación
    DND_FILES, TkinterDnD = None, None

from submp4.nucleo.audio import (
    DURACION_PRUEBA,
    NIVELES,
    ErrorAudio,
    PistaAudio,
    analizar_audio,
    elegir_pista,
    mejorar_audio,
    probar_fragmento,
)
from submp4.nucleo.conversion import (
    FORMATOS_ENTRADA,
    ErrorConversion,
    LecturaSubtitulo,
    convertir_a_srt,
    leer_lineas,
    ruta_srt_disponible,
)
from submp4.nucleo.sincronizacion import (
    AjusteLineal,
    ajuste_por_dos_puntos,
    ajuste_por_punto,
    ajuste_por_segundos,
    describir_ajuste,
    ruta_sincronizada_disponible,
    sincronizar_archivo,
)
from submp4.nucleo.ffmpeg import buscar_ffmpeg
from submp4.nucleo.idiomas import IDIOMAS
from submp4.nucleo.tiempo import ms_a_texto
from submp4.nucleo.unir_video import ErrorUnion, PistaSubtitulo, unir_subtitulos

# Filtros para el cuadro de "Buscar…" de Windows.
_TIPOS_SUBTITULO = [
    ("Subtítulos", " ".join(f"*{ext}" for ext in FORMATOS_ENTRADA)),
    ("Todos los archivos", "*.*"),
]
_TIPOS_VIDEO = [("Video MP4", "*.mp4")]

# Opciones de "pista activa al abrir el video".
_ACTIVA_1 = "Subtítulo 1"
_ACTIVA_2 = "Subtítulo 2"
_ACTIVA_BILINGUE = "Bilingüe"
_ACTIVA_NINGUNA = "Ninguna"

# Intensidades de "Mejorar audio" y su explicación.
_AYUDA_NIVELES = {
    "Suave": "Cambio leve: el sonido se parece al original, pero sin golpes tan fuertes.",
    "Media": "Recomendado: voces claras y efectos controlados.",
    "Fuerte": "Voces al frente y efectos bajos. Ideal para ver de noche o con audífonos.",
}

# Nombres de los tres modos de sincronización.
_MODO_SEGUNDOS = "Por segundos"
_MODO_PUNTO = "Por un punto"
_MODO_DOS_PUNTOS = "Por dos puntos"


class SelectorArchivo(ctk.CTkFrame):
    """Una fila con: etiqueta, caja de texto con la ruta y botón "Buscar…".

    al_elegir: función opcional que se llama cuando se elige un archivo.
    """

    def __init__(self, padre, texto: str, tipos: list[tuple[str, str]], al_elegir=None):
        super().__init__(padre, fg_color="transparent")
        self._tipos = tipos
        self._al_elegir = al_elegir
        # Extensiones aceptadas, sacadas de los filtros (ej. {".srt", ".ass"}).
        self._extensiones = {
            patron[1:].lower()
            for _, patrones in tipos
            for patron in patrones.split()
            if patron != "*.*"
        }

        self._etiqueta = ctk.CTkLabel(self, text=texto, width=110, anchor="w")
        self._etiqueta.pack(side="left")
        self.entrada = ctk.CTkEntry(self, placeholder_text="Ningún archivo seleccionado")
        self.entrada.pack(side="left", fill="x", expand=True, padx=8)
        ctk.CTkButton(self, text="Buscar…", width=90, command=self._buscar).pack(side="left")

    def activar_arrastrar(self) -> None:
        """Permite soltar un archivo sobre esta fila (etiqueta o caja de texto)."""
        for widget in (self, self._etiqueta, self.entrada):
            # Los widgets de CustomTkinter están hechos de piezas internas de
            # tkinter (_canvas, _entry, _label); el archivo cae sobre ellas.
            for pieza in (widget, *(getattr(widget, n, None) for n in ("_canvas", "_entry", "_label"))):
                if pieza is not None:
                    pieza.drop_target_register(DND_FILES)
                    pieza.dnd_bind("<<Drop>>", self._al_soltar)
        self.entrada.configure(placeholder_text="Arrastra un archivo aquí o usa «Buscar…»")

    def _al_soltar(self, evento):
        """Recibe el archivo soltado. Si sueltan varios, se usa el primero."""
        # tkinter entrega las rutas en un solo texto, con {llaves} si tienen espacios.
        archivos = self.tk.splitlist(evento.data)
        if not archivos:
            return evento.action
        ruta = archivos[0]
        if self._extensiones and Path(ruta).suffix.lower() not in self._extensiones:
            messagebox.showwarning(
                "Archivo no válido",
                f"Aquí solo se aceptan: {', '.join(sorted(self._extensiones))}",
            )
            return evento.action
        self.poner_ruta(ruta)
        return evento.action

    def _buscar(self) -> None:
        ruta = filedialog.askopenfilename(filetypes=self._tipos)
        if ruta:  # Si el usuario cancela, ruta es una cadena vacía.
            self.poner_ruta(ruta)

    def poner_ruta(self, ruta) -> None:
        """Escribe la ruta en la caja y avisa con al_elegir."""
        _poner_texto(self.entrada, str(ruta))
        if self._al_elegir:
            self._al_elegir(str(ruta))

    @property
    def ruta(self) -> str:
        return self.entrada.get().strip()


def _poner_texto(entrada, texto: str) -> None:
    """Reemplaza el contenido de una caja de texto."""
    entrada.delete(0, "end")
    entrada.insert(0, texto)


def _pedir_donde_guardar(sugerida: Path, titulo: str) -> str:
    """Abre la ventana "Guardar como" de Windows con un nombre ya sugerido.

    Empieza en la carpeta del archivo original. Si el usuario elige un
    archivo que ya existe, Windows le pregunta si quiere reemplazarlo.
    Devuelve la ruta elegida, o "" si el usuario cancela.
    """
    return filedialog.asksaveasfilename(
        title=titulo,
        initialdir=str(sugerida.parent),
        initialfile=sugerida.name,
        defaultextension=".srt",
        filetypes=[("Subtítulo SubRip", "*.srt")],
    )


def _resumen_linea(texto: str, largo: int = 45) -> str:
    """Texto corto de una línea para mostrar: sin etiquetas y en un renglón."""
    plano = re.sub(r"</?[ibu]>", "", texto).replace("\n", " / ")
    return plano if len(plano) <= largo else plano[: largo - 1] + "…"


class TareaEnSegundoPlano:
    """Corre un trabajo largo con FFmpeg sin congelar la ventana (RF-13c).

    El trabajo corre en otro hilo y NUNCA toca la ventana: solo deja mensajes
    en una cola. La ventana revisa la cola cada 100 ms y actualiza el botón,
    la barra de progreso y el texto (tkinter solo se puede usar desde el hilo
    principal).
    """

    def __init__(self, ventana, boton, barra, etiqueta, texto_trabajando: str):
        self._ventana = ventana
        self._boton = boton
        self._barra = barra
        self._etiqueta = etiqueta
        self._texto_trabajando = texto_trabajando
        self._texto_boton = ""
        self._cola: queue.Queue = queue.Queue()
        self._con_avance = False
        self._al_terminar = None
        self.ocupada = False

    def iniciar(self, trabajo, al_terminar, boton=None) -> None:
        """trabajo(al_progresar) hace el proceso y devuelve un resultado.

        al_terminar(resultado) devuelve el mensaje de éxito para mostrar.
        boton: botón que se desactiva mientras tanto (por defecto el principal).
        """
        self.ocupada = True
        self._al_terminar = al_terminar
        self._boton_activo = boton or self._boton
        self._texto_boton = self._boton_activo.cget("text")
        self._boton_activo.configure(state="disabled", text="Trabajando…")
        self._etiqueta.configure(text=self._texto_trabajando)
        self._barra.configure(mode="indeterminate")
        self._barra.start()
        self._con_avance = False

        def en_otro_hilo():
            try:
                resultado = trabajo(lambda avance: self._cola.put(("avance", avance)))
                self._cola.put(("listo", resultado))
            except (ErrorUnion, ErrorAudio, OSError) as error:
                self._cola.put(("error", str(error)))
            except Exception as error:  # noqa: BLE001
                # Cualquier otro error: avisar igual, para que la ventana no
                # quede trabada en "Trabajando…" (y se pueda cerrar).
                self._cola.put(("error", f"Error inesperado: {type(error).__name__}: {error}"))

        threading.Thread(target=en_otro_hilo, daemon=True).start()
        self._ventana.after(100, self._revisar)

    def _revisar(self) -> None:
        terminado = False
        try:
            while True:
                tipo, dato = self._cola.get_nowait()
                if tipo == "avance":
                    if not self._con_avance:  # Pasar de "animada" a porcentaje
                        self._barra.stop()
                        self._barra.configure(mode="determinate")
                        self._con_avance = True
                    self._barra.set(dato)
                    self._etiqueta.configure(text=f"{self._texto_trabajando} {dato:.0%}")
                elif tipo == "listo":
                    try:
                        mensaje = self._al_terminar(dato)
                    except Exception as error:  # noqa: BLE001 - la tarea sí terminó bien
                        mensaje = f"✔ Terminado (aviso al mostrar el resultado: {error})"
                    self._terminar(mensaje, avance=1)
                    terminado = True
                elif tipo == "error":
                    self._terminar(f"⚠ {dato}", avance=0)
                    terminado = True
        except queue.Empty:
            pass
        if not terminado:
            self._ventana.after(100, self._revisar)

    def _terminar(self, mensaje: str, avance: float) -> None:
        self.ocupada = False
        self._barra.stop()
        self._barra.configure(mode="determinate")
        self._barra.set(avance)
        self._boton_activo.configure(state="normal", text=self._texto_boton)
        self._etiqueta.configure(text=mensaje)


class VentanaPrincipal(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("SubtitulosMP4")
        self.geometry("800x660")
        self.minsize(680, 620)
        self._arrastrar_disponible = self._cargar_arrastrar()

        # Subtítulo leído en la pestaña Sincronizar (para vista previa).
        self._sinc_lectura: LecturaSubtitulo | None = None
        self._sinc_ruta_leida = ""

        # Pistas de audio del video elegido en "Mejorar audio".
        self._audio_pistas: list[PistaAudio] = []
        self._audio_ruta_leida = ""
        self.protocol("WM_DELETE_WINDOW", self._al_cerrar)

        pestañas = ctk.CTkTabview(self)
        pestañas.pack(fill="both", expand=True, padx=12, pady=(12, 0))

        self._crear_pestaña_convertir(pestañas.add("Convertir"))
        self._crear_pestaña_sincronizar(pestañas.add("Sincronizar"))
        self._crear_pestaña_unir(pestañas.add("Unir al video"))
        self._crear_pestaña_audio(pestañas.add("Mejorar audio"))
        self._crear_barra_estado()

        if self._arrastrar_disponible:
            for selector in (
                self.conv_entrada, self.sinc_entrada, self.unir_video, self.unir_sub,
                self.unir_sub2, self.audio_video,
            ):
                selector.activar_arrastrar()

    def _cargar_arrastrar(self) -> bool:
        """Activa arrastrar y soltar si tkinterdnd2 está disponible (RF-17)."""
        if TkinterDnD is None:
            return False
        try:
            TkinterDnD._require(self)  # Carga la extensión tkdnd en esta ventana
        except (RuntimeError, tkinter.TclError):
            return False
        return True

    # ======================================================================
    # Pestaña 1: Convertir (fase 1)
    # ======================================================================
    def _crear_pestaña_convertir(self, pestaña) -> None:
        ctk.CTkLabel(
            pestaña,
            text="Convierte ASS, SSA, VTT, SUB… a SRT limpio y en UTF-8.",
        ).pack(anchor="w", pady=(8, 12))
        self.conv_entrada = SelectorArchivo(pestaña, "Subtítulo:", _TIPOS_SUBTITULO)
        self.conv_entrada.pack(fill="x", pady=4)

        fila_fps = ctk.CTkFrame(pestaña, fg_color="transparent")
        fila_fps.pack(fill="x", pady=4)
        ctk.CTkLabel(fila_fps, text="FPS del video:", width=110, anchor="w").pack(side="left")
        self.conv_fps = ctk.CTkEntry(fila_fps, width=120, placeholder_text="ej. 23.976")
        self.conv_fps.pack(side="left", padx=8)
        ctk.CTkLabel(
            fila_fps, text="(solo para archivos .sub; déjalo vacío en los demás)", text_color="gray"
        ).pack(side="left")

        ctk.CTkButton(pestaña, text="Convertir a SRT", command=self._convertir).pack(pady=16)
        self.conv_resultado = ctk.CTkLabel(pestaña, text="", justify="left")
        self.conv_resultado.pack(anchor="w")

    def _convertir(self) -> None:
        """Convierte el subtítulo elegido y muestra un resumen."""
        if not self.conv_entrada.ruta:
            self.conv_resultado.configure(text="⚠ Primero elige un subtítulo con «Buscar…».")
            return

        texto_fps = self.conv_fps.get().strip().replace(",", ".")
        try:
            fps = float(texto_fps) if texto_fps else None
        except ValueError:
            self.conv_resultado.configure(text="⚠ Los FPS deben ser un número, ej. 23.976")
            return

        ruta = self.conv_entrada.ruta
        try:
            # Revisar que se pueda leer ANTES de preguntar dónde guardar.
            leer_lineas(ruta, fps)
            destino = _pedir_donde_guardar(ruta_srt_disponible(ruta), "Guardar subtítulo convertido")
            if not destino:
                self.conv_resultado.configure(text="Cancelado: no se guardó nada.")
                return
            resultado = convertir_a_srt(ruta, ruta_salida=destino, fps=fps)
        except ErrorConversion as error:
            self.conv_resultado.configure(text=f"⚠ {error}")
            return
        except OSError as error:  # Sin permisos, disco lleno, etc.
            self.conv_resultado.configure(text=f"⚠ No se pudo guardar el archivo: {error}")
            return

        self.conv_resultado.configure(
            text=(
                f"✔ Guardado como: {resultado.ruta_salida.name}\n"
                f"   En la carpeta: {resultado.ruta_salida.parent}\n"
                f"   Leído como {resultado.formato_origen.upper()} "
                f"({resultado.codificacion_origen})\n"
                f"   {resultado.lineas_guardadas} líneas guardadas, "
                f"{resultado.efectos_quitados} letreros/efectos quitados"
            )
        )
        # Dejar el SRT nuevo listo en las otras pestañas.
        self.sinc_entrada.poner_ruta(resultado.ruta_salida)
        self.unir_sub.poner_ruta(resultado.ruta_salida)

    # ======================================================================
    # Pestaña 2: Sincronizar (fase 2)
    # ======================================================================
    def _crear_pestaña_sincronizar(self, pestaña) -> None:
        self.sinc_entrada = SelectorArchivo(
            pestaña, "Subtítulo:", _TIPOS_SUBTITULO, al_elegir=self._leer_para_sincronizar
        )
        self.sinc_entrada.pack(fill="x", pady=(8, 4))

        # Primera y última línea del archivo, para saber qué buscar en el video.
        self.sinc_info = ctk.CTkLabel(pestaña, text="", justify="left", text_color="gray")
        self.sinc_info.pack(anchor="w", pady=(0, 8))

        self.sinc_modo = ctk.CTkSegmentedButton(
            pestaña,
            values=[_MODO_SEGUNDOS, _MODO_PUNTO, _MODO_DOS_PUNTOS],
            command=self._mostrar_modo,
        )
        self.sinc_modo.pack(pady=4)

        # Un panel por modo; solo se ve el del modo elegido.
        contenedor = ctk.CTkFrame(pestaña, fg_color="transparent")
        contenedor.pack(fill="x", pady=8)
        self._paneles = {
            _MODO_SEGUNDOS: self._crear_panel_segundos(contenedor),
            _MODO_PUNTO: self._crear_panel_punto(contenedor),
            _MODO_DOS_PUNTOS: self._crear_panel_dos_puntos(contenedor),
        }

        botones = ctk.CTkFrame(pestaña, fg_color="transparent")
        botones.pack(pady=8)
        ctk.CTkButton(botones, text="Vista previa", command=self._vista_previa).pack(
            side="left", padx=6
        )
        ctk.CTkButton(botones, text="Aplicar al archivo", command=self._sincronizar).pack(
            side="left", padx=6
        )

        self.sinc_resultado = ctk.CTkLabel(pestaña, text="", justify="left")
        self.sinc_resultado.pack(anchor="w")

        self.sinc_modo.set(_MODO_PUNTO)
        self._mostrar_modo(_MODO_PUNTO)

    def _crear_panel_segundos(self, padre):
        panel = ctk.CTkFrame(padre, fg_color="transparent")
        ctk.CTkLabel(panel, text="Mover (segundos):").grid(row=0, column=0, sticky="w")
        self.sinc_segundos = ctk.CTkEntry(panel, width=120, placeholder_text="+2.5 o -1,5")
        self.sinc_segundos.grid(row=0, column=1, padx=8, pady=4)
        ctk.CTkLabel(
            panel,
            text="Positivo: aparece más tarde · Negativo: aparece antes",
            text_color="gray",
        ).grid(row=1, column=0, columnspan=2, sticky="w")
        return panel

    def _crear_panel_punto(self, padre):
        panel = ctk.CTkFrame(padre, fg_color="transparent")
        ctk.CTkLabel(panel, text="El subtítulo empieza en:").grid(row=0, column=0, sticky="w")
        self.sinc_sub = ctk.CTkEntry(panel, width=120, placeholder_text="00:00:06")
        self.sinc_sub.grid(row=0, column=1, padx=8, pady=4)
        ctk.CTkLabel(panel, text="Empiezan a hablar en:").grid(row=1, column=0, sticky="w")
        self.sinc_real = ctk.CTkEntry(panel, width=120, placeholder_text="00:01:23")
        self.sinc_real.grid(row=1, column=1, padx=8, pady=4)
        return panel

    def _crear_panel_dos_puntos(self, padre):
        panel = ctk.CTkFrame(padre, fg_color="transparent")
        ctk.CTkLabel(panel, text="En el subtítulo").grid(row=0, column=1)
        ctk.CTkLabel(panel, text="En el video").grid(row=0, column=2)

        ctk.CTkLabel(panel, text="Primera línea:").grid(row=1, column=0, sticky="w")
        self.sinc_sub_1 = ctk.CTkEntry(panel, width=120, placeholder_text="00:00:06")
        self.sinc_sub_1.grid(row=1, column=1, padx=8, pady=4)
        self.sinc_real_1 = ctk.CTkEntry(panel, width=120, placeholder_text="00:01:23")
        self.sinc_real_1.grid(row=1, column=2, padx=8, pady=4)

        ctk.CTkLabel(panel, text="Última línea:").grid(row=2, column=0, sticky="w")
        self.sinc_sub_2 = ctk.CTkEntry(panel, width=120, placeholder_text="00:42:10")
        self.sinc_sub_2.grid(row=2, column=1, padx=8, pady=4)
        self.sinc_real_2 = ctk.CTkEntry(panel, width=120, placeholder_text="00:43:55")
        self.sinc_real_2.grid(row=2, column=2, padx=8, pady=4)
        return panel

    def _mostrar_modo(self, modo: str) -> None:
        """Muestra solo el panel del modo elegido."""
        for nombre, panel in self._paneles.items():
            if nombre == modo:
                panel.pack(anchor="w")
            else:
                panel.pack_forget()
        self.sinc_resultado.configure(text="")

    def _leer_para_sincronizar(self, ruta: str) -> bool:
        """Lee el subtítulo, muestra su primera y última línea y llena los tiempos.

        Devuelve True si se pudo leer.
        """
        self._sinc_lectura = None
        try:
            lectura = leer_lineas(ruta)
        except ErrorConversion as error:
            # Los .sub necesitan FPS: esos se ingresan en la pestaña Convertir.
            consejo = " Conviértelo primero en la pestaña Convertir." if "FPS" in str(error) else ""
            self.sinc_info.configure(text=f"⚠ {error}{consejo}")
            return False
        except OSError as error:
            self.sinc_info.configure(text=f"⚠ No se pudo leer el archivo: {error}")
            return False

        if not lectura.lineas:
            self.sinc_info.configure(text="⚠ El archivo no tiene líneas de diálogo.")
            return False

        self._sinc_lectura = lectura
        self._sinc_ruta_leida = ruta
        primera, ultima = lectura.lineas[0], lectura.lineas[-1]
        self.sinc_info.configure(
            text=(
                f"Primera línea ({ms_a_texto(primera.inicio)}): {_resumen_linea(primera.texto)}\n"
                f"Última línea ({ms_a_texto(ultima.inicio)}): {_resumen_linea(ultima.texto)}"
            )
        )
        # Llenar los tiempos "en el subtítulo"; solo falta escribir los del video.
        _poner_texto(self.sinc_sub, ms_a_texto(primera.inicio))
        _poner_texto(self.sinc_sub_1, ms_a_texto(primera.inicio))
        _poner_texto(self.sinc_sub_2, ms_a_texto(ultima.inicio))
        return True

    def _ajuste_elegido(self) -> AjusteLineal:
        """Calcula el ajuste según el modo elegido. Lanza ValueError si falta algo."""
        modo = self.sinc_modo.get()
        if modo == _MODO_SEGUNDOS:
            return ajuste_por_segundos(self.sinc_segundos.get())
        if modo == _MODO_PUNTO:
            return ajuste_por_punto(self.sinc_sub.get(), self.sinc_real.get())
        return ajuste_por_dos_puntos(
            self.sinc_sub_1.get(), self.sinc_real_1.get(),
            self.sinc_sub_2.get(), self.sinc_real_2.get(),
        )

    def _vista_previa(self) -> None:
        """Explica el ajuste y muestra cómo quedarían la primera y la última línea."""
        try:
            ajuste = self._ajuste_elegido()
        except ValueError as error:
            self.sinc_resultado.configure(text=f"⚠ {error}")
            return

        texto = describir_ajuste(ajuste)
        ruta = self.sinc_entrada.ruta
        if ruta and ruta != self._sinc_ruta_leida:
            self._leer_para_sincronizar(ruta)  # La ruta se escribió a mano
        if self._sinc_lectura and not ajuste.sin_cambios:
            primera, ultima = self._sinc_lectura.lineas[0], self._sinc_lectura.lineas[-1]
            texto += (
                f"\nPrimera línea: {ms_a_texto(primera.inicio)} → "
                f"{ms_a_texto(max(0, ajuste.aplicar(primera.inicio)))}"
                f"\nÚltima línea: {ms_a_texto(ultima.inicio)} → "
                f"{ms_a_texto(max(0, ajuste.aplicar(ultima.inicio)))}"
            )
        self.sinc_resultado.configure(text=texto)

    def _sincronizar(self) -> None:
        """Aplica el ajuste al archivo y guarda un SRT nuevo."""
        ruta = self.sinc_entrada.ruta
        if not ruta:
            self.sinc_resultado.configure(text="⚠ Primero elige un subtítulo con «Buscar…».")
            return
        try:
            ajuste = self._ajuste_elegido()
        except ValueError as error:
            self.sinc_resultado.configure(text=f"⚠ {error}")
            return
        if ajuste.sin_cambios:
            self.sinc_resultado.configure(text="El ajuste no mueve nada; no se creó ningún archivo.")
            return

        try:
            # Revisar que se pueda leer ANTES de preguntar dónde guardar.
            leer_lineas(ruta)
            destino = _pedir_donde_guardar(
                ruta_sincronizada_disponible(ruta), "Guardar subtítulo sincronizado"
            )
            if not destino:
                self.sinc_resultado.configure(text="Cancelado: no se guardó nada.")
                return
            resultado = sincronizar_archivo(ruta, ajuste, ruta_salida=destino)
        except ErrorConversion as error:
            self.sinc_resultado.configure(text=f"⚠ {error}")
            return
        except OSError as error:
            self.sinc_resultado.configure(text=f"⚠ No se pudo guardar el archivo: {error}")
            return

        texto = (
            f"✔ Guardado como: {resultado.ruta_salida.name}\n"
            f"   En la carpeta: {resultado.ruta_salida.parent}\n"
            f"   {resultado.lineas_guardadas} líneas"
        )
        if resultado.lineas_recortadas or resultado.lineas_eliminadas:
            texto += (
                f" ({resultado.lineas_recortadas} recortadas y "
                f"{resultado.lineas_eliminadas} eliminadas por quedar antes del segundo 0)"
            )
        self.sinc_resultado.configure(text=texto)
        self.unir_sub.poner_ruta(resultado.ruta_salida)  # Listo para unir

    # ======================================================================
    # Pestaña 3: Unir al video (fase 3)
    # ======================================================================
    def _crear_pestaña_unir(self, pestaña) -> None:
        self.unir_video = SelectorArchivo(pestaña, "Video MP4:", _TIPOS_VIDEO)
        self.unir_video.pack(fill="x", pady=(8, 4))

        # Dos pistas: normalmente inglés y español. La segunda es opcional.
        self.unir_sub, self.unir_idioma_1 = self._crear_fila_pista(pestaña, "Subtítulo 1:", "Inglés")
        self.unir_sub2, self.unir_idioma_2 = self._crear_fila_pista(
            pestaña, "Subtítulo 2:", "Español"
        )
        ctk.CTkLabel(
            pestaña, text="El subtítulo 2 es opcional. Acepta SRT, ASS, VTT…", text_color="gray"
        ).pack(anchor="w")

        fila_activa = ctk.CTkFrame(pestaña, fg_color="transparent")
        fila_activa.pack(fill="x", pady=(10, 4))
        ctk.CTkLabel(fila_activa, text="Activo al abrir:", width=110, anchor="w").pack(side="left")
        self.unir_activa = ctk.CTkSegmentedButton(
            fila_activa, values=[_ACTIVA_1, _ACTIVA_2, _ACTIVA_BILINGUE, _ACTIVA_NINGUNA]
        )
        self.unir_activa.set(_ACTIVA_1)
        self.unir_activa.pack(side="left", padx=8)

        self.unir_conservar = ctk.CTkCheckBox(
            pestaña, text="Conservar los subtítulos que ya trae el video"
        )
        self.unir_conservar.select()  # Marcado por defecto
        self.unir_conservar.pack(anchor="w", pady=(6, 2))

        # Fase 4: pista extra con el subtítulo 1 arriba y el 2 en cursiva debajo.
        self.unir_bilingue = ctk.CTkCheckBox(
            pestaña,
            text="Agregar también una pista bilingüe (subtítulo 1 arriba, subtítulo 2 en cursiva)",
        )
        self.unir_bilingue.pack(anchor="w", pady=(2, 6))

        self.unir_boton = ctk.CTkButton(
            pestaña, text="Unir subtítulos al video", command=self._unir
        )
        self.unir_boton.pack(pady=8)
        self.unir_barra = ctk.CTkProgressBar(pestaña)
        self.unir_barra.set(0)
        self.unir_barra.pack(fill="x", padx=4, pady=4)
        self.unir_resultado = ctk.CTkLabel(
            pestaña,
            text="Se crea un archivo nuevo; el video original no se toca.",
            justify="left",
        )
        self.unir_resultado.pack(anchor="w")
        self._tarea_unir = TareaEnSegundoPlano(
            self, self.unir_boton, self.unir_barra, self.unir_resultado, "Uniendo…"
        )

    def _crear_fila_pista(self, padre, texto: str, idioma: str):
        """Fila con selector de subtítulo + menú de idioma."""
        fila = ctk.CTkFrame(padre, fg_color="transparent")
        fila.pack(fill="x", pady=4)
        selector = SelectorArchivo(fila, texto, _TIPOS_SUBTITULO)
        selector.pack(side="left", fill="x", expand=True)
        menu_idioma = ctk.CTkOptionMenu(fila, values=list(IDIOMAS), width=130)
        menu_idioma.set(idioma)
        menu_idioma.pack(side="left", padx=(8, 0))
        return selector, menu_idioma

    def _unir(self) -> None:
        """Valida lo elegido y lanza la unión en segundo plano."""
        if self._hay_tarea_activa(self.unir_resultado):
            return
        if not self.unir_video.ruta:
            self.unir_resultado.configure(text="⚠ Primero elige el video MP4.")
            return

        # Solo las filas que tienen un archivo elegido.
        filas = [
            (selector, menu)
            for selector, menu in ((self.unir_sub, self.unir_idioma_1), (self.unir_sub2, self.unir_idioma_2))
            if selector.ruta
        ]
        if not filas:
            self.unir_resultado.configure(text="⚠ Elige al menos un subtítulo.")
            return
        pistas = [PistaSubtitulo(selector.ruta, IDIOMAS[menu.get()]) for selector, menu in filas]
        selectores = [selector for selector, _ in filas]

        bilingue = bool(self.unir_bilingue.get())
        if bilingue and len(filas) != 2:
            self.unir_resultado.configure(
                text="⚠ Para la pista bilingüe elige los dos subtítulos (ej. inglés y español)."
            )
            return

        # Qué pista queda activa: su posición dentro de las pistas elegidas.
        # Orden final: subtítulo 1, subtítulo 2 y, al final, la bilingüe.
        activa = self.unir_activa.get()
        if activa == _ACTIVA_NINGUNA:
            por_defecto = None
        elif activa == _ACTIVA_BILINGUE:
            if not bilingue:
                self.unir_resultado.configure(
                    text="⚠ Elegiste la bilingüe como activa: marca «Agregar también una pista bilingüe»."
                )
                return
            por_defecto = len(pistas)
        else:
            objetivo = self.unir_sub if activa == _ACTIVA_1 else self.unir_sub2
            if objetivo not in selectores:
                self.unir_resultado.configure(
                    text=f"⚠ Elegiste el {activa.lower()} como activo, pero está vacío."
                )
                return
            por_defecto = selectores.index(objetivo)

        video, conservar = self.unir_video.ruta, bool(self.unir_conservar.get())

        def trabajo(al_progresar):
            return unir_subtitulos(
                video, pistas, por_defecto, conservar,
                al_progresar=al_progresar, incluir_bilingue=bilingue,
            )

        def al_terminar(resultado) -> str:
            # Dejar el video listo en "Mejorar audio", si ese campo está vacío.
            if not self.audio_video.ruta:
                self.audio_video.poner_ruta(resultado.ruta_salida)
            return (
                f"✔ Listo: {resultado.ruta_salida.name}\n"
                f"   Guardado junto al video, en: {resultado.ruta_salida.parent}\n"
                f"   {resultado.pistas_agregadas} pista(s) de subtítulos agregada(s). "
                "Ábrelo en VLC o MX Player y elige el subtítulo en el menú."
            )

        self._tarea_unir.iniciar(trabajo, al_terminar)

    def _hay_tarea_activa(self, etiqueta) -> bool:
        """True (y avisa) si ya hay un proceso de FFmpeg trabajando.

        Se hace uno a la vez: dos procesos sobre videos grandes al mismo
        tiempo serían más lentos que uno tras otro.
        """
        if self._tarea_unir.ocupada or self._tarea_audio.ocupada:
            etiqueta.configure(text="⚠ Espera a que termine el proceso que está en curso.")
            return True
        return False

    def _al_cerrar(self) -> None:
        """No dejar cerrar la ventana a mitad de un proceso (quedaría un archivo dañado)."""
        if self._tarea_unir.ocupada or self._tarea_audio.ocupada:
            messagebox.showwarning(
                "Espera un momento", "Hay un video procesándose. Espera a que termine."
            )
            return
        self.destroy()

    # ======================================================================
    # Pestaña 4: Mejorar audio (fase 5)
    # ======================================================================
    def _crear_pestaña_audio(self, pestaña) -> None:
        ctk.CTkLabel(
            pestaña,
            text="Voces más claras y efectos (explosiones, disparos) menos fuertes.",
        ).pack(anchor="w", pady=(8, 6))
        self.audio_video = SelectorArchivo(
            pestaña, "Video MP4:", _TIPOS_VIDEO, al_elegir=self._analizar_audio
        )
        self.audio_video.pack(fill="x", pady=4)

        fila_pista = ctk.CTkFrame(pestaña, fg_color="transparent")
        fila_pista.pack(fill="x", pady=4)
        ctk.CTkLabel(fila_pista, text="Pista de audio:", width=110, anchor="w").pack(side="left")
        self.audio_pista = ctk.CTkOptionMenu(
            fila_pista, values=["Primero elige un video"], command=self._mostrar_metodo_audio
        )
        self.audio_pista.configure(state="disabled")
        self.audio_pista.pack(side="left", fill="x", expand=True, padx=8)
        self.audio_info = ctk.CTkLabel(pestaña, text="", justify="left", text_color="gray")
        self.audio_info.pack(anchor="w")

        fila_nivel = ctk.CTkFrame(pestaña, fg_color="transparent")
        fila_nivel.pack(fill="x", pady=(8, 2))
        ctk.CTkLabel(fila_nivel, text="Intensidad:", width=110, anchor="w").pack(side="left")
        self.audio_nivel = ctk.CTkSegmentedButton(
            fila_nivel, values=list(NIVELES), command=self._mostrar_ayuda_nivel
        )
        self.audio_nivel.set("Media")
        self.audio_nivel.pack(side="left", padx=8)
        self.audio_ayuda_nivel = ctk.CTkLabel(
            pestaña, text=_AYUDA_NIVELES["Media"], text_color="gray"
        )
        self.audio_ayuda_nivel.pack(anchor="w")

        self.audio_conservar = ctk.CTkCheckBox(
            pestaña, text="Conservar también el audio original (para cambiar entre ambos en VLC)"
        )
        self.audio_conservar.select()
        self.audio_conservar.pack(anchor="w", pady=6)

        # Fragmento de prueba: escuchar antes de procesar toda la película.
        fila_prueba = ctk.CTkFrame(pestaña, fg_color="transparent")
        fila_prueba.pack(fill="x", pady=4)
        ctk.CTkLabel(fila_prueba, text="Probar desde:", width=110, anchor="w").pack(side="left")
        self.audio_inicio = ctk.CTkEntry(fila_prueba, width=110, placeholder_text="00:10:00")
        self.audio_inicio.pack(side="left", padx=8)
        self.audio_boton_prueba = ctk.CTkButton(
            fila_prueba,
            text=f"Probar {DURACION_PRUEBA // 60} minutos",
            width=140,
            command=self._probar_audio,
        )
        self.audio_boton_prueba.pack(side="left")
        ctk.CTkLabel(
            fila_prueba, text="  (elige una escena con diálogos y efectos)", text_color="gray"
        ).pack(side="left")

        self.audio_boton = ctk.CTkButton(
            pestaña, text="Mejorar audio de todo el video", command=self._mejorar_audio
        )
        self.audio_boton.pack(pady=8)
        self.audio_barra = ctk.CTkProgressBar(pestaña)
        self.audio_barra.set(0)
        self.audio_barra.pack(fill="x", padx=4, pady=4)
        self.audio_resultado = ctk.CTkLabel(
            pestaña,
            text="Se crea un video nuevo junto al original; el original no se toca.",
            justify="left",
        )
        self.audio_resultado.pack(anchor="w")
        self._tarea_audio = TareaEnSegundoPlano(
            self, self.audio_boton, self.audio_barra, self.audio_resultado,
            "Procesando el audio…",
        )

    def _analizar_audio(self, ruta: str) -> None:
        """Lee las pistas de audio del video y llena el menú (RF-22)."""
        self._audio_pistas = []
        self._audio_ruta_leida = ""
        self.audio_pista.configure(values=["Primero elige un video"], state="disabled")
        self.audio_pista.set("Primero elige un video")
        try:
            pistas = analizar_audio(ruta)
        except ErrorAudio as error:
            self.audio_info.configure(text=f"⚠ {error}")
            return

        self._audio_pistas = pistas
        self._audio_ruta_leida = ruta
        descripciones = [pista.descripcion() for pista in pistas]
        self.audio_pista.configure(values=descripciones, state="normal")
        elegida = descripciones[elegir_pista(pistas)]
        self.audio_pista.set(elegida)
        self._mostrar_metodo_audio(elegida)

    def _pista_elegida(self) -> PistaAudio | None:
        descripciones = [pista.descripcion() for pista in self._audio_pistas]
        actual = self.audio_pista.get()
        if actual not in descripciones:
            return None
        return self._audio_pistas[descripciones.index(actual)]

    def _mostrar_metodo_audio(self, _valor=None) -> None:
        """Explica qué se le va a hacer a la pista elegida."""
        pista = self._pista_elegida()
        if pista is None:
            return
        if pista.es_envolvente:
            texto = (f"Audio {pista.distribucion}: se subirá el canal central (donde van las voces) "
                     "y se bajarán los demás.")
        elif pista.canales == 2:
            texto = "Audio estéreo: se reducirán los sonidos de los lados y se nivelará el volumen."
            if any(otra.es_envolvente for otra in self._audio_pistas):
                texto += "\nEste video también tiene una pista 5.1: si es del mismo idioma, elígela."
        else:
            texto = "Se nivelará el volumen."
        if pista.ya_mejorada:
            texto += "\nOjo: esta pista ya fue mejorada antes. Mejor elige la original."
        self.audio_info.configure(text=texto)

    def _mostrar_ayuda_nivel(self, nivel: str) -> None:
        self.audio_ayuda_nivel.configure(text=_AYUDA_NIVELES[nivel])

    def _datos_audio(self):
        """Valida lo elegido. Devuelve (video, número de pista, nivel) o None."""
        if self._hay_tarea_activa(self.audio_resultado):
            return None
        video = self.audio_video.ruta
        if not video:
            self.audio_resultado.configure(text="⚠ Primero elige el video MP4.")
            return None
        if video != self._audio_ruta_leida:
            self._analizar_audio(video)  # La ruta se escribió a mano
        pista = self._pista_elegida()
        if pista is None:
            # Mostrar la causa real (no existe, está dañado, no tiene audio…).
            causa = self.audio_info.cget("text") or "⚠ No se encontró audio en ese video."
            self.audio_resultado.configure(text=causa)
            return None
        return video, pista.numero, self.audio_nivel.get()

    def _probar_audio(self) -> None:
        """Procesa solo 2 minutos para escuchar el resultado antes (RF-26)."""
        datos = self._datos_audio()
        if datos is None:
            return
        video, numero, nivel = datos
        inicio = self.audio_inicio.get().strip() or "00:10:00"

        def trabajo(al_progresar):
            return probar_fragmento(video, inicio, nivel, numero, al_progresar)

        def al_terminar(resultado) -> str:
            return (
                f"✔ Prueba lista: {resultado.ruta_salida.name}\n"
                f"   En: {resultado.ruta_salida.parent}\n"
                "   Ábrela en VLC. En Audio → Pista de audio compara la mejorada con la original."
            )

        self._tarea_audio.iniciar(trabajo, al_terminar, boton=self.audio_boton_prueba)

    def _mejorar_audio(self) -> None:
        """Procesa el audio de todo el video (RF-21)."""
        datos = self._datos_audio()
        if datos is None:
            return
        video, numero, nivel = datos
        conservar = bool(self.audio_conservar.get())

        def trabajo(al_progresar):
            return mejorar_audio(video, nivel, numero, conservar, al_progresar)

        def al_terminar(resultado) -> str:
            # Dejar el video listo en "Unir al video", si ese campo está vacío.
            if not self.unir_video.ruta:
                self.unir_video.poner_ruta(resultado.ruta_salida)
            originales = (" La pista original sigue disponible en Audio → Pista de audio."
                          if resultado.conservo_originales else "")
            return (
                f"✔ Listo: {resultado.ruta_salida.name}\n"
                f"   Guardado junto al video, en: {resultado.ruta_salida.parent}\n"
                f"   {resultado.metodo}.{originales}"
            )

        self._tarea_audio.iniciar(trabajo, al_terminar)

    # ======================================================================
    # Barra inferior: estado de FFmpeg (RF-16)
    # ======================================================================
    def _crear_barra_estado(self) -> None:
        if buscar_ffmpeg():
            texto, color = "✔ FFmpeg encontrado", "green"
        else:
            texto = "✖ FFmpeg no está instalado (necesario para unir al video y mejorar el audio). Ver README."
            color = "orange"
        ctk.CTkLabel(self, text=texto, text_color=color).pack(anchor="w", padx=16, pady=8)


def iniciar() -> None:
    """Abre la ventana y la mantiene abierta hasta que el usuario la cierre."""
    ctk.set_appearance_mode("system")  # Claro u oscuro, según Windows.
    VentanaPrincipal().mainloop()
