"""Orquestador: une captura -> cola -> transcripción -> escritura.

Expone una API simple para la UI (`iniciar`, `detener`) y hace el trabajo
pesado (cargar modelo, drenar audio pendiente) en hilos para no congelar la
interfaz. Toda comunicación hacia la UI va por callbacks.
"""

from __future__ import annotations

import queue
import threading
from datetime import datetime
from typing import Callable

from transcriptor.audio import CanalLoopback, CanalMicrofono, indice_microfono
from transcriptor.config import Configuracion
from transcriptor.escritor import EscritorMarkdown
from transcriptor.modelos import Hablante, Segmento
from transcriptor.transcripcion import MotorWhisper, TrabajadorTranscripcion


class Grabador:
    def __init__(
        self,
        on_segmento: Callable[[Segmento], None],
        on_estado: Callable[[str], None],
        on_inicio_ok: Callable[[], None],
        on_fin: Callable[[str | None], None],
    ):
        self.on_segmento = on_segmento
        self.on_estado = on_estado
        self.on_inicio_ok = on_inicio_ok
        self.on_fin = on_fin

        self._motor: MotorWhisper | None = None
        self._modelo_cargado: str | None = None  # qué modelo tiene en memoria
        self._cola: "queue.Queue" = queue.Queue()
        self._canales: list[CanalCaptura] = []
        self._trabajador: TrabajadorTranscripcion | None = None
        self._escritor: EscritorMarkdown | None = None
        self._grabando = False

    @property
    def grabando(self) -> bool:
        return self._grabando

    # -- Arranque ---------------------------------------------------------- #
    def iniciar(self, cfg: Configuracion) -> None:
        """Arranca en segundo plano: carga el modelo si hace falta y luego captura."""
        if self._grabando:
            return
        threading.Thread(target=self._iniciar_sync, args=(cfg,), daemon=True).start()

    def _iniciar_sync(self, cfg: Configuracion) -> None:
        try:
            if self._motor is None or self._modelo_cargado != cfg.modelo:
                self.on_estado(f"⏳ Cargando modelo «{cfg.modelo}»… (la primera vez descarga, puede tardar)")
                self._motor = MotorWhisper(cfg)
                self._modelo_cargado = cfg.modelo

            self._escritor = EscritorMarkdown(cfg, datetime.now())

            def _entregar(seg: Segmento) -> None:
                self._escritor.agregar(seg)
                self.on_segmento(seg)

            self._trabajador = TrabajadorTranscripcion(
                self._motor, self._cola, cfg, _entregar, self.on_estado
            )
            self._trabajador.start()

            # La reunión (loopback, vía soundcard) siempre se captura.
            # El canal crea su propio objeto soundcard dentro de su hilo (COM).
            self._canales = [CanalLoopback(cfg.nombre_altavoz, Hablante.PARTICIPANTES, cfg, self._cola)]

            # Tu micrófono (vía sounddevice) solo si usas audífonos
            # (si no, captaría el eco de la reunión por los parlantes).
            if cfg.audifonos:
                idx = indice_microfono(cfg.nombre_mic)
                self._canales.insert(0, CanalMicrofono(idx, Hablante.YO, cfg, self._cola))

            for c in self._canales:
                c.start()

            self._grabando = True
            modo = "mic + reunión" if cfg.audifonos else "solo reunión (sin mic)"
            self.on_estado(f"🔴 Grabando [{modo}] — guardando en: {self._escritor.ruta}")
            self.on_inicio_ok()
        except Exception as exc:  # noqa: BLE001
            self.on_estado(f"❌ No se pudo iniciar: {exc}")
            self.on_fin(None)

    # -- Parada ------------------------------------------------------------ #
    def detener(self) -> None:
        if not self._grabando:
            return
        self._grabando = False
        threading.Thread(target=self._detener_sync, daemon=True).start()

    def _detener_sync(self) -> None:
        for c in self._canales:
            c.detener()
        for c in self._canales:
            c.join(timeout=3)

        if self._trabajador:
            self.on_estado("⏳ Procesando el audio pendiente…")
            self._trabajador.detener()
            self._trabajador.join(timeout=300)

        ruta = self._escritor.finalizar(datetime.now()) if self._escritor else None
        self._canales = []
        self.on_estado(f"✅ Listo. Transcripción guardada en: {ruta}" if ruta else "Detenido.")
        self.on_fin(ruta)
