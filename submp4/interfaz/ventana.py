"""Ventana principal de la app, hecha con CustomTkinter (RF-14 a RF-16).

Estado: la pestaña Convertir ya funciona (fase 1). En Sincronizar ya se
calcula el desplazamiento por un punto; "Aplicar" y "Unir" se conectan en
las fases 2 y 3.
"""

from tkinter import filedialog, messagebox

import customtkinter as ctk

from submp4.nucleo.conversion import FORMATOS_ENTRADA, ErrorConversion, convertir_a_srt
from submp4.nucleo.sincronizacion import desplazamiento_por_punto
from submp4.nucleo.tiempo import ms_a_texto
from submp4.nucleo.unir_video import buscar_ffmpeg

# Filtros para el cuadro de "Buscar…" de Windows.
_TIPOS_SUBTITULO = [
    ("Subtítulos", " ".join(f"*{ext}" for ext in FORMATOS_ENTRADA)),
    ("Todos los archivos", "*.*"),
]
_TIPOS_SRT = [("SubRip", "*.srt")]
_TIPOS_VIDEO = [("Video MP4", "*.mp4")]


class SelectorArchivo(ctk.CTkFrame):
    """Una fila con: etiqueta, caja de texto con la ruta y botón "Buscar…"."""

    def __init__(self, padre, texto: str, tipos: list[tuple[str, str]]):
        super().__init__(padre, fg_color="transparent")
        self._tipos = tipos

        ctk.CTkLabel(self, text=texto, width=110, anchor="w").pack(side="left")
        self.entrada = ctk.CTkEntry(self, placeholder_text="Ningún archivo seleccionado")
        self.entrada.pack(side="left", fill="x", expand=True, padx=8)
        ctk.CTkButton(self, text="Buscar…", width=90, command=self._buscar).pack(side="left")

    def _buscar(self) -> None:
        ruta = filedialog.askopenfilename(filetypes=self._tipos)
        if ruta:  # Si el usuario cancela, ruta es una cadena vacía.
            self.entrada.delete(0, "end")
            self.entrada.insert(0, ruta)

    @property
    def ruta(self) -> str:
        return self.entrada.get().strip()


def _proximamente(fase: int) -> None:
    messagebox.showinfo("En construcción", f"Esta función llega en la fase {fase}.")


class VentanaPrincipal(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("SubtitulosMP4")
        self.geometry("760x470")
        self.minsize(640, 440)

        pestañas = ctk.CTkTabview(self)
        pestañas.pack(fill="both", expand=True, padx=12, pady=(12, 0))

        self._crear_pestaña_convertir(pestañas.add("Convertir"))
        self._crear_pestaña_sincronizar(pestañas.add("Sincronizar"))
        self._crear_pestaña_unir(pestañas.add("Unir al video"))
        self._crear_barra_estado()

    # ---------- Pestaña 1: Convertir (fase 1) ----------
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
        for selector in (self.sinc_entrada, self.unir_sub):
            selector.entrada.delete(0, "end")
            selector.entrada.insert(0, str(resultado.ruta_salida))

    # ---------- Pestaña 2: Sincronizar (fase 2) ----------
    def _crear_pestaña_sincronizar(self, pestaña) -> None:
        self.sinc_entrada = SelectorArchivo(pestaña, "Subtítulo SRT:", _TIPOS_SRT)
        self.sinc_entrada.pack(fill="x", pady=(8, 12))

        fila = ctk.CTkFrame(pestaña, fg_color="transparent")
        fila.pack(fill="x", pady=4)
        ctk.CTkLabel(fila, text="El subtítulo empieza en:").grid(row=0, column=0, sticky="w")
        self.sinc_sub = ctk.CTkEntry(fila, width=120, placeholder_text="00:00:06")
        self.sinc_sub.grid(row=0, column=1, padx=8, pady=4)
        ctk.CTkLabel(fila, text="Empiezan a hablar en:").grid(row=1, column=0, sticky="w")
        self.sinc_real = ctk.CTkEntry(fila, width=120, placeholder_text="00:01:23")
        self.sinc_real.grid(row=1, column=1, padx=8, pady=4)

        botones = ctk.CTkFrame(pestaña, fg_color="transparent")
        botones.pack(pady=12)
        ctk.CTkButton(botones, text="Calcular", command=self._calcular).pack(side="left", padx=6)
        ctk.CTkButton(
            botones, text="Aplicar al archivo", command=lambda: _proximamente(2)
        ).pack(side="left", padx=6)

        self.sinc_resultado = ctk.CTkLabel(pestaña, text="")
        self.sinc_resultado.pack()

    def _calcular(self) -> None:
        """Muestra cuánto hay que mover el subtítulo. Esto ya funciona."""
        try:
            ms = desplazamiento_por_punto(self.sinc_sub.get(), self.sinc_real.get())
        except ValueError as error:
            self.sinc_resultado.configure(text=f"⚠ {error}")
            return

        if ms > 0:
            texto = f"Hay que ATRASAR el subtítulo {ms_a_texto(ms)}"
        elif ms < 0:
            texto = f"Hay que ADELANTAR el subtítulo {ms_a_texto(-ms)}"
        else:
            texto = "El subtítulo ya está sincronizado."
        self.sinc_resultado.configure(text=texto)

    # ---------- Pestaña 3: Unir al video (fase 3) ----------
    def _crear_pestaña_unir(self, pestaña) -> None:
        self.unir_video = SelectorArchivo(pestaña, "Video MP4:", _TIPOS_VIDEO)
        self.unir_video.pack(fill="x", pady=(8, 4))
        self.unir_sub = SelectorArchivo(pestaña, "Subtítulo SRT:", _TIPOS_SRT)
        self.unir_sub.pack(fill="x", pady=4)
        ctk.CTkLabel(
            pestaña, text="Se crea un archivo nuevo; el video original no se toca."
        ).pack(anchor="w", pady=8)
        ctk.CTkButton(
            pestaña, text="Unir subtítulo al video", command=lambda: _proximamente(3)
        ).pack(pady=8)

    # ---------- Barra inferior: estado de FFmpeg (RF-16) ----------
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
