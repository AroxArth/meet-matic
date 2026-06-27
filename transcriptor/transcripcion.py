"""Motor de transcripción (faster-whisper) y el hilo trabajador que consume
los segmentos de audio de la cola y los convierte en texto.
"""

from __future__ import annotations

import queue
import threading
from typing import Callable

import numpy as np
from faster_whisper import WhisperModel

from transcriptor.audio import ERROR
from transcriptor.config import Configuracion
from transcriptor.modelos import Hablante, Segmento


class MotorWhisper:
    """Envoltorio fino sobre faster-whisper. Cargar el modelo es lo lento;
    transcribir un fragmento corto es rápido.
    """

    def __init__(self, cfg: Configuracion):
        self.cfg = cfg
        # La primera vez descarga el modelo desde HuggingFace (requiere internet
        # esa única vez). Después funciona 100% offline.
        self.model = WhisperModel(
            cfg.modelo, device=cfg.device, compute_type=cfg.compute_type,
            cpu_threads=cfg.cpu_threads,
        )

    def transcribir(self, audio: np.ndarray, idioma: str | None) -> str:
        segmentos, _info = self.model.transcribe(
            audio,
            language=idioma,
            beam_size=1,                      # greedy: más rápido para tiempo real
            vad_filter=True,                  # recorta silencios y reduce alucinaciones
            condition_on_previous_text=False,  # cada fragmento es independiente
            task="transcribe",
        )
        return " ".join(s.text.strip() for s in segmentos).strip()


class TrabajadorTranscripcion(threading.Thread):
    """Consume (hablante, audio, inicio, fin) de la cola y entrega Segmentos."""

    def __init__(
        self,
        motor: MotorWhisper,
        cola_entrada: "queue.Queue",
        cfg: Configuracion,
        on_segmento: Callable[[Segmento], None],
        on_estado: Callable[[str], None],
    ):
        super().__init__(daemon=True, name="transcripcion")
        self.motor = motor
        self.cola = cola_entrada
        self.cfg = cfg
        self.on_segmento = on_segmento
        self.on_estado = on_estado
        self._activo = True
        self._min_muestras = int(cfg.min_segmento_s * cfg.samplerate)

    def detener(self) -> None:
        # Deja de aceptar trabajo nuevo, pero vacía lo pendiente antes de salir.
        self._activo = False

    def run(self) -> None:
        while self._activo or not self.cola.empty():
            try:
                hablante, audio, inicio, fin = self.cola.get(timeout=0.3)
            except queue.Empty:
                continue

            if hablante == ERROR:
                self.on_estado(f"⚠️ Error de audio ({audio})")
                continue

            if not isinstance(audio, np.ndarray) or audio.size < self._min_muestras:
                continue  # demasiado corto: ruido, no voz

            try:
                texto = self.motor.transcribir(audio, self.cfg.idioma)
            except Exception as exc:  # noqa: BLE001
                self.on_estado(f"⚠️ Error transcribiendo: {exc}")
                continue

            if texto:
                self.on_segmento(Segmento(hablante=hablante, inicio=inicio, fin=fin, texto=texto))
