"""Ventana principal de la app, hecha con CustomTkinter (RF-14 a RF-16).

Las tres pestañas funcionan: Convertir (fase 1), Sincronizar (fase 2) y
Unir al video (fase 3).
"""

import queue
import re
import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk

from submp4.nucleo.conversion import (
    FORMATOS_ENTRADA,
    ErrorConversion,
    LecturaSubtitulo,
    convertir_a_srt,
    leer_lineas,
)
from submp4.nucleo.sincronizacion import (
    AjusteLineal,
    ajuste_por_dos_puntos,
    ajuste_por_punto,
    ajuste_por_segundos,
    describir_ajuste,
    sincronizar_archivo,
)
from submp4.nucleo.tiempo import ms_a_texto
from submp4.nucleo.unir_video import (
    IDIOMAS,
    ErrorUnion,
    PistaSubtitulo,
    buscar_ffmpeg,
    unir_subtitulos,
)

# Filtros para el cuadro de "Buscar…" de Windows.
_TIPOS_SUBTITULO = [
    ("Subtítulos", " ".join(f"*{ext}" for ext in FORMATOS_ENTRADA)),
    ("Todos los archivos", "*.*"),
]
_TIPOS_VIDEO = [("Video MP4", "*.mp4")]

# Opciones de "pista activa al abrir el video".
_ACTIVA_1 = "Subtítulo 1"
_ACTIVA_2 = "Subtítulo 2"
_ACTIVA_NINGUNA = "Ninguna"

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

        ctk.CTkLabel(self, text=texto, width=110, anchor="w").pack(side="left")
        self.entrada = ctk.CTkEntry(self, placeholder_text="Ningún archivo seleccionado")
        self.entrada.pack(side="left", fill="x", expand=True, padx=8)
        ctk.CTkButton(self, text="Buscar…", width=90, command=self._buscar).pack(side="left")

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


def _resumen_linea(texto: str, largo: int = 45) -> str:
    """Texto corto de una línea para mostrar: sin etiquetas y en un renglón."""
    plano = re.sub(r"</?[ibu]>", "", texto).replace("\n", " / ")
    return plano if len(plano) <= largo else plano[: largo - 1] + "…"


class VentanaPrincipal(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("SubtitulosMP4")
        self.geometry("780x540")
        self.minsize(660, 500)

        # Subtítulo leído en la pestaña Sincronizar (para vista previa).
        self._sinc_lectura: LecturaSubtitulo | None = None
        self._sinc_ruta_leida = ""

        # La unión corre en segundo plano; se comunica con la ventana por una cola.
        self._uniendo = False
        self._cola_union: queue.Queue = queue.Queue()
        self.protocol("WM_DELETE_WINDOW", self._al_cerrar)

        pestañas = ctk.CTkTabview(self)
        pestañas.pack(fill="both", expand=True, padx=12, pady=(12, 0))

        self._crear_pestaña_convertir(pestañas.add("Convertir"))
        self._crear_pestaña_sincronizar(pestañas.add("Sincronizar"))
        self._crear_pestaña_unir(pestañas.add("Unir al video"))
        self._crear_barra_estado()

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

        try:
            resultado = convertir_a_srt(self.conv_entrada.ruta, fps=fps)
        except ErrorConversion as error:
            self.conv_resultado.configure(text=f"⚠ {error}")
            return
        except OSError as error:  # Sin permisos, disco lleno, etc.
            self.conv_resultado.configure(text=f"⚠ No se pudo guardar el archivo: {error}")
            return

        self.conv_resultado.configure(
            text=(
                f"✔ Guardado como: {resultado.ruta_salida.name}\n"
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
            resultado = sincronizar_archivo(ruta, ajuste)
        except ErrorConversion as error:
            self.sinc_resultado.configure(text=f"⚠ {error}")
            return
        except OSError as error:
            self.sinc_resultado.configure(text=f"⚠ No se pudo guardar el archivo: {error}")
            return

        texto = f"✔ Guardado como: {resultado.ruta_salida.name}\n   {resultado.lineas_guardadas} líneas"
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
            fila_activa, values=[_ACTIVA_1, _ACTIVA_2, _ACTIVA_NINGUNA]
        )
        self.unir_activa.set(_ACTIVA_1)
        self.unir_activa.pack(side="left", padx=8)

        self.unir_conservar = ctk.CTkCheckBox(
            pestaña, text="Conservar los subtítulos que ya trae el video"
        )
        self.unir_conservar.select()  # Marcado por defecto
        self.unir_conservar.pack(anchor="w", pady=6)

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
        if self._uniendo:
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

        # Qué pista queda activa: su posición dentro de las pistas elegidas.
        activa = self.unir_activa.get()
        if activa == _ACTIVA_NINGUNA:
            por_defecto = None
        else:
            objetivo = self.unir_sub if activa == _ACTIVA_1 else self.unir_sub2
            if objetivo not in selectores:
                self.unir_resultado.configure(
                    text=f"⚠ Elegiste el {activa.lower()} como activo, pero está vacío."
                )
                return
            por_defecto = selectores.index(objetivo)

        # Preparar la ventana mientras FFmpeg trabaja.
        self._uniendo = True
        self.unir_boton.configure(state="disabled", text="Uniendo…")
        self.unir_resultado.configure(text="Uniendo… esto suele tardar unos segundos.")
        self.unir_barra.configure(mode="indeterminate")
        self.unir_barra.start()
        self._barra_con_avance = False

        hilo = threading.Thread(
            target=self._trabajo_union,
            args=(self.unir_video.ruta, pistas, por_defecto, bool(self.unir_conservar.get())),
            daemon=True,
        )
        hilo.start()
        self.after(100, self._revisar_cola_union)

    def _trabajo_union(self, video, pistas, por_defecto, conservar) -> None:
        """Corre en segundo plano. NO toca la ventana: solo deja mensajes en la cola."""
        try:
            resultado = unir_subtitulos(
                video, pistas, por_defecto, conservar,
                al_progresar=lambda avance: self._cola_union.put(("avance", avance)),
            )
            self._cola_union.put(("listo", resultado))
        except (ErrorUnion, OSError) as error:
            self._cola_union.put(("error", str(error)))

    def _revisar_cola_union(self) -> None:
        """Lee los mensajes del trabajo en segundo plano y actualiza la ventana."""
        terminado = False
        try:
            while True:
                tipo, dato = self._cola_union.get_nowait()
                if tipo == "avance":
                    if not self._barra_con_avance:  # Pasar de "animada" a porcentaje
                        self.unir_barra.stop()
                        self.unir_barra.configure(mode="determinate")
                        self._barra_con_avance = True
                    self.unir_barra.set(dato)
                    self.unir_resultado.configure(text=f"Uniendo… {dato:.0%}")
                elif tipo == "listo":
                    self._terminar_union(
                        f"✔ Listo: {dato.ruta_salida.name}\n"
                        f"   {dato.pistas_agregadas} pista(s) de subtítulos agregada(s). "
                        "Ábrelo en VLC o MX Player y elige el subtítulo en el menú.",
                        avance=1,
                    )
                    terminado = True
                elif tipo == "error":
                    self._terminar_union(f"⚠ {dato}", avance=0)
                    terminado = True
        except queue.Empty:
            pass
        if not terminado:
            self.after(100, self._revisar_cola_union)

    def _terminar_union(self, mensaje: str, avance: float) -> None:
        self._uniendo = False
        self.unir_barra.stop()
        self.unir_barra.configure(mode="determinate")
        self.unir_barra.set(avance)
        self.unir_boton.configure(state="normal", text="Unir subtítulos al video")
        self.unir_resultado.configure(text=mensaje)

    def _al_cerrar(self) -> None:
        """No dejar cerrar la ventana a mitad de una unión (quedaría un archivo dañado)."""
        if self._uniendo:
            messagebox.showwarning(
                "Espera un momento", "Se están uniendo los subtítulos. Espera a que termine."
            )
            return
        self.destroy()

    # ======================================================================
    # Barra inferior: estado de FFmpeg (RF-16)
    # ======================================================================
    def _crear_barra_estado(self) -> None:
        if buscar_ffmpeg():
            texto, color = "✔ FFmpeg encontrado", "green"
        else:
            texto = "✖ FFmpeg no está instalado (necesario para unir al video). Ver README."
            color = "orange"
        ctk.CTkLabel(self, text=texto, text_color=color).pack(anchor="w", padx=16, pady=8)


def iniciar() -> None:
    """Abre la ventana y la mantiene abierta hasta que el usuario la cierre."""
    ctk.set_appearance_mode("system")  # Claro u oscuro, según Windows.
    VentanaPrincipal().mainloop()
