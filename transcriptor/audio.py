"""Captura de audio de dos fuentes con segmentación por voz (VAD por energía).

Arquitectura híbrida (cada librería en lo que es buena en Windows):
  - Micrófono (tu voz)  -> sounddevice / PortAudio. Maneja formatos de mic que
    `soundcard` rompe con un assert (p.ej. webcams como la Logitech Brio).
  - Loopback (la reunión) -> soundcard / WASAPI. Captura lo que suena por los
    altavoces, que es justo lo que sounddevice no hace de forma sencilla.

Cada canal corre en su hilo, lee bloques pequeños, detecta voz y, al cerrarse
un segmento (silencio suficiente o longitud máxima), lo empuja a una cola
compartida para que el transcriptor lo procese.
"""

from __future__ import annotations

import ctypes
import queue
import threading

import numpy as np
import sounddevice as sd
import soundcard as sc

from transcriptor.config import Configuracion
from transcriptor.modelos import Hablante

# Sentinela que un canal pone en la cola si falla la captura.
ERROR = "__error__"


def _com_init() -> None:
    """Inicializa COM en el hilo actual. soundcard (WASAPI/Media Foundation) usa
    COM y EXIGE que cada hilo que lo toque haya llamado a CoInitialize. Si no,
    falla con 0x800401f0 (CO_E_NOTINITIALIZED).
    """
    try:
        ctypes.windll.ole32.CoInitialize(None)
    except Exception:  # noqa: BLE001 - si ya estaba inicializado, seguimos
        pass


def _com_fin() -> None:
    try:
        ctypes.windll.ole32.CoUninitialize()
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------- #
# Selección de dispositivos
# --------------------------------------------------------------------------- #
def _entradas_sounddevice() -> dict[str, int]:
    """Mapa {nombre -> índice} de micrófonos. Filtra a WASAPI cuando existe, para
    evitar los duplicados y nombres truncados de MME/DirectSound.
    """
    apis = sd.query_hostapis()
    wasapi = next((i for i, a in enumerate(apis) if "WASAPI" in a["name"]), None)
    vistos: dict[str, int] = {}
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] <= 0:
            continue
        if wasapi is not None and d["hostapi"] != wasapi:
            continue
        vistos.setdefault(d["name"], i)
    return vistos


def listar_microfonos() -> list[str]:
    return list(_entradas_sounddevice().keys())


def listar_altavoces() -> list[str]:
    return [s.name for s in sc.all_speakers()]


def indice_microfono(nombre: str | None) -> int | None:
    """Índice de sounddevice para el nombre dado. None = micrófono por defecto."""
    if not nombre:
        return None
    return _entradas_sounddevice().get(nombre)


def obtener_loopback(nombre_altavoz: str | None):
    """Captura lo que SUENA por los altavoces (la voz de los participantes).

    Se hace pidiendo el micrófono-loopback asociado al altavoz.
    """
    altavoz = None
    if nombre_altavoz:
        for s in sc.all_speakers():
            if s.name == nombre_altavoz:
                altavoz = s
                break
    if altavoz is None:
        altavoz = sc.default_speaker()
    return sc.get_microphone(id=str(altavoz.name), include_loopback=True)


# --------------------------------------------------------------------------- #
# VAD por energía (con umbral adaptativo al ruido de fondo)
# --------------------------------------------------------------------------- #
class SegmentadorVoz:
    """Máquina de estados: acumula bloques mientras hay voz y devuelve el
    audio completo cuando detecta un silencio que cierra la frase.
    """

    def __init__(self, cfg: Configuracion):
        self.sr = cfg.samplerate
        self.block_size = int(cfg.samplerate * cfg.block_ms / 1000)
        self.bloques_corte = max(1, int(cfg.silencio_corte_ms / cfg.block_ms))
        self.max_muestras = int(cfg.max_segmento_s * cfg.samplerate)
        self.umbral_base = cfg.umbral_voz
        self.noise_floor = 0.001
        self._reset()

    def _reset(self) -> None:
        self.buffer: list[np.ndarray] = []
        self.pre_roll: list[np.ndarray] = []  # lookback para no cortar el ataque de la palabra
        self.bloques_silencio = 0
        self.en_voz = False

    def procesar(self, bloque: np.ndarray) -> np.ndarray | None:
        """Devuelve el audio de un segmento cerrado, o None si aún no hay nada."""
        rms = float(np.sqrt(np.mean(bloque**2))) if bloque.size else 0.0
        umbral = max(self.umbral_base, self.noise_floor * 3.0 + 0.004)
        es_voz = rms >= umbral

        if not es_voz:
            # Solo aprendemos el ruido de fondo en los silencios.
            self.noise_floor = 0.9 * self.noise_floor + 0.1 * rms

        if not self.en_voz:
            self.pre_roll.append(bloque)
            if len(self.pre_roll) > 3:  # ~300 ms de pre-roll
                self.pre_roll.pop(0)
            if es_voz:
                self.en_voz = True
                self.buffer = list(self.pre_roll)
                self.pre_roll = []
                self.bloques_silencio = 0
            return None

        # Estamos dentro de una frase.
        self.buffer.append(bloque)
        self.bloques_silencio = 0 if es_voz else self.bloques_silencio + 1

        muestras = sum(b.size for b in self.buffer)
        if self.bloques_silencio >= self.bloques_corte or muestras >= self.max_muestras:
            audio = np.concatenate(self.buffer)
            self._reset()
            return audio
        return None

    def flush(self) -> np.ndarray | None:
        """Cierra lo que quede pendiente al detener la grabación."""
        audio = np.concatenate(self.buffer) if (self.en_voz and self.buffer) else None
        self._reset()
        return audio


# --------------------------------------------------------------------------- #
# Canales de captura (un hilo por fuente)
# --------------------------------------------------------------------------- #
class _CanalBase(threading.Thread):
    """Lógica común: segmentar bloques y emitir segmentos a la cola.

    Las subclases solo implementan `run()` con la captura propia de su librería
    y llaman a `_alimentar(bloque)` por cada bloque mono float32 leído.
    """

    def __init__(self, hablante: Hablante, cfg: Configuracion, cola: "queue.Queue"):
        super().__init__(daemon=True, name=f"captura-{hablante.value}")
        self.hablante = hablante
        self.cfg = cfg
        self.cola = cola
        self.segmentador = SegmentadorVoz(cfg)
        self._activo = threading.Event()
        self._activo.set()
        self._muestras = 0

    def detener(self) -> None:
        self._activo.clear()

    def _alimentar(self, bloque: np.ndarray) -> None:
        self._muestras += bloque.size
        audio = self.segmentador.procesar(bloque)
        if audio is not None:
            self._emitir(audio)

    def _flush(self) -> None:
        audio = self.segmentador.flush()
        if audio is not None:
            self._emitir(audio)

    def _emitir(self, audio: np.ndarray) -> None:
        fin = self._muestras / self.cfg.samplerate
        inicio = fin - audio.size / self.cfg.samplerate
        self.cola.put((self.hablante, np.ascontiguousarray(audio), inicio, fin))

    def _error(self, exc: Exception) -> None:
        self.cola.put((ERROR, f"{self.hablante.value}: {exc}", 0.0, 0.0))


class CanalMicrofono(_CanalBase):
    """Tu voz, vía sounddevice (PortAudio). PortAudio remuestrea a 16 kHz solo."""

    def __init__(self, indice_dispositivo: int | None, hablante: Hablante,
                 cfg: Configuracion, cola: "queue.Queue"):
        super().__init__(hablante, cfg, cola)
        self.indice = indice_dispositivo

    def run(self) -> None:
        bs = self.segmentador.block_size
        _com_init()  # PortAudio/WASAPI también usa COM en este hilo
        try:
            with sd.InputStream(
                samplerate=self.cfg.samplerate, blocksize=bs, channels=1,
                dtype="float32", device=self.indice,
            ) as stream:
                while self._activo.is_set():
                    datos, _ = stream.read(bs)
                    self._alimentar(datos[:, 0].astype(np.float32))
                self._flush()
        except Exception as exc:  # noqa: BLE001 - reportamos a la UI, no reventamos el hilo
            self._error(exc)
        finally:
            _com_fin()


class CanalLoopback(_CanalBase):
    """El audio de la reunión, vía soundcard (WASAPI loopback).

    El objeto de soundcard se crea DENTRO de este hilo (tras CoInitialize) para
    que todo su uso de COM viva en el mismo hilo inicializado.
    """

    def __init__(self, nombre_altavoz: str | None, hablante: Hablante,
                 cfg: Configuracion, cola: "queue.Queue"):
        super().__init__(hablante, cfg, cola)
        self.nombre_altavoz = nombre_altavoz

    def run(self) -> None:
        bs = self.segmentador.block_size
        _com_init()
        try:
            microfono = obtener_loopback(self.nombre_altavoz)
            # channels=None -> canales nativos (loopback suele ser estéreo); luego mono.
            with microfono.recorder(samplerate=self.cfg.samplerate, channels=None, blocksize=bs) as rec:
                while self._activo.is_set():
                    datos = rec.record(numframes=bs)
                    bloque = datos.mean(axis=1).astype(np.float32) if datos.ndim > 1 else datos.astype(np.float32)
                    self._alimentar(bloque)
                self._flush()
        except Exception as exc:  # noqa: BLE001
            self._error(exc)
        finally:
            _com_fin()
