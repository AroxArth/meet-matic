"""Interfaz gráfica con CustomTkinter.

La UI vive en el hilo principal. Los hilos de fondo (captura/transcripción)
NO tocan widgets directamente: envían eventos a una cola que la UI drena con
`after()`. Así evitamos las condiciones de carrera de Tkinter.
"""

from __future__ import annotations

import queue

import customtkinter as ctk

from transcriptor.audio import listar_altavoces, listar_microfonos
from transcriptor.config import IDIOMAS, MODELOS, Configuracion
from transcriptor.grabador import Grabador
from transcriptor.modelos import Segmento

ctk.set_appearance_mode("system")
ctk.set_default_color_theme("blue")

_AUTO = "Automático"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Transcriptor de Reuniones")
        self.geometry("820x680")
        self.minsize(720, 600)

        self._eventos: "queue.Queue" = queue.Queue()
        self.grabador = Grabador(
            on_segmento=lambda s: self._eventos.put(("seg", s)),
            on_estado=lambda m: self._eventos.put(("estado", m)),
            on_inicio_ok=lambda: self._eventos.put(("inicio_ok", None)),
            on_fin=lambda r: self._eventos.put(("fin", r)),
        )

        self._construir()
        self.after(120, self._drenar_eventos)
        self.protocol("WM_DELETE_WINDOW", self._al_cerrar)

    # ------------------------------------------------------------------ UI -- #
    def _construir(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # --- Panel de configuración ---
        cfg = ctk.CTkFrame(self)
        cfg.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="ew")
        cfg.grid_columnconfigure(1, weight=1)
        cfg.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(cfg, text="Nombre de la reunión").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.entry_nombre = ctk.CTkEntry(cfg, placeholder_text="Ej: Kickoff Cliente Acme")
        self.entry_nombre.grid(row=0, column=1, columnspan=3, padx=10, pady=10, sticky="ew")

        ctk.CTkLabel(cfg, text="Idioma").grid(row=1, column=0, padx=10, pady=10, sticky="w")
        self.var_idioma = ctk.StringVar(value="Español")
        ctk.CTkOptionMenu(cfg, values=list(IDIOMAS), variable=self.var_idioma).grid(
            row=1, column=1, padx=10, pady=10, sticky="ew"
        )

        ctk.CTkLabel(cfg, text="Modelo").grid(row=1, column=2, padx=10, pady=10, sticky="w")
        self.var_modelo = ctk.StringVar(value="base")
        ctk.CTkOptionMenu(cfg, values=MODELOS, variable=self.var_modelo).grid(
            row=1, column=3, padx=10, pady=10, sticky="ew"
        )

        ctk.CTkLabel(cfg, text="Micrófono (Yo)").grid(row=2, column=0, padx=10, pady=10, sticky="w")
        self.var_mic = ctk.StringVar(value=_AUTO)
        self.opt_mic = ctk.CTkOptionMenu(cfg, values=[_AUTO, *listar_microfonos()], variable=self.var_mic)
        self.opt_mic.grid(row=2, column=1, padx=10, pady=10, sticky="ew")

        ctk.CTkLabel(cfg, text="Altavoz (Reunión)").grid(row=2, column=2, padx=10, pady=10, sticky="w")
        self.var_altavoz = ctk.StringVar(value=_AUTO)
        ctk.CTkOptionMenu(cfg, values=[_AUTO, *listar_altavoces()], variable=self.var_altavoz).grid(
            row=2, column=3, padx=10, pady=10, sticky="ew"
        )

        # --- ¿Audífonos? Decide si capturamos tu micrófono ---
        self.var_audifonos = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(
            cfg, text="🎧 Tengo audífonos puestos",
            variable=self.var_audifonos, command=self._actualizar_hint,
        ).grid(row=3, column=0, columnspan=2, padx=10, pady=(4, 12), sticky="w")

        self.lbl_hint = ctk.CTkLabel(
            cfg, text="", anchor="w", justify="left", text_color="gray", wraplength=400,
        )
        self.lbl_hint.grid(row=3, column=2, columnspan=2, padx=10, pady=(4, 12), sticky="ew")

        # --- Controles ---
        ctrl = ctk.CTkFrame(self)
        ctrl.grid(row=1, column=0, padx=16, pady=8, sticky="ew")
        ctrl.grid_columnconfigure(2, weight=1)

        self.btn_iniciar = ctk.CTkButton(ctrl, text="▶  Iniciar", width=140, command=self._iniciar)
        self.btn_iniciar.grid(row=0, column=0, padx=10, pady=10)

        self.btn_detener = ctk.CTkButton(
            ctrl, text="⏹  Detener", width=140, command=self._detener,
            state="disabled", fg_color="#b3261e", hover_color="#8c1d18",
        )
        self.btn_detener.grid(row=0, column=1, padx=10, pady=10)

        self.lbl_estado = ctk.CTkLabel(ctrl, text="Listo.", anchor="w")
        self.lbl_estado.grid(row=0, column=2, padx=10, pady=10, sticky="ew")

        # --- Transcripción en vivo ---
        self.txt = ctk.CTkTextbox(self, wrap="word", font=("Consolas", 13))
        self.txt.grid(row=2, column=0, padx=16, pady=(8, 16), sticky="nsew")
        self.txt.configure(state="disabled")

        self._actualizar_hint()

    def _actualizar_hint(self) -> None:
        """Muestra en vivo qué se va a capturar según el interruptor de audífonos."""
        if self.var_audifonos.get():
            self.lbl_hint.configure(
                text="✓ Se transcriben tu voz (Yo) y la reunión (Participantes) por separado.",
            )
            self.opt_mic.configure(state="normal")
        else:
            self.lbl_hint.configure(
                text="⚠️ Sin audífonos: solo se transcribe la reunión. Tu micrófono se desactiva "
                "para evitar el eco — tu voz NO quedará en el .md.",
            )
            self.opt_mic.configure(state="disabled")

    # -------------------------------------------------------------- acciones -- #
    def _config_actual(self) -> Configuracion:
        mic = self.var_mic.get()
        alt = self.var_altavoz.get()
        return Configuracion(
            nombre_reunion=self.entry_nombre.get().strip() or "Reunión sin título",
            idioma=IDIOMAS[self.var_idioma.get()],
            modelo=self.var_modelo.get(),
            nombre_mic=None if mic == _AUTO else mic,
            nombre_altavoz=None if alt == _AUTO else alt,
            audifonos=self.var_audifonos.get(),
        )

    def _iniciar(self) -> None:
        self.btn_iniciar.configure(state="disabled")
        self._set_config_estado("disabled")
        self._append("\n" + "─" * 60 + "\n")
        self.grabador.iniciar(self._config_actual())

    def _detener(self) -> None:
        self.btn_detener.configure(state="disabled")
        self.grabador.detener()

    def _al_cerrar(self) -> None:
        if self.grabador.grabando:
            self.grabador.detener()
        self.destroy()

    # ---------------------------------------------------------------- eventos -- #
    def _drenar_eventos(self) -> None:
        try:
            while True:
                tipo, dato = self._eventos.get_nowait()
                if tipo == "estado":
                    self.lbl_estado.configure(text=dato)
                elif tipo == "seg":
                    self._mostrar_segmento(dato)
                elif tipo == "inicio_ok":
                    self.btn_detener.configure(state="normal")
                elif tipo == "fin":
                    self.btn_iniciar.configure(state="normal")
                    self.btn_detener.configure(state="disabled")
                    self._set_config_estado("normal")
        except queue.Empty:
            pass
        self.after(120, self._drenar_eventos)

    def _mostrar_segmento(self, s: Segmento) -> None:
        ts = f"{int(s.inicio) // 60:02d}:{int(s.inicio) % 60:02d}"
        self._append(f"[{ts}] {s.hablante.value}: {s.texto}\n")

    def _append(self, texto: str) -> None:
        self.txt.configure(state="normal")
        self.txt.insert("end", texto)
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def _set_config_estado(self, estado: str) -> None:
        self.entry_nombre.configure(state=estado)


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
