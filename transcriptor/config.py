"""Configuración de una sesión de transcripción.

Una sola fuente de verdad para todos los parámetros. La UI construye una
instancia de `Configuracion` y se la pasa al `Grabador`.
"""

from __future__ import annotations

from dataclasses import dataclass

# Mapa visible-en-UI -> código de idioma de Whisper. None = autodetección.
IDIOMAS: dict[str, str | None] = {
    "Español": "es",
    "English": "en",
    "Auto (detectar)": None,
}

# Modelos disponibles, de más rápido/menos preciso a más lento/más preciso.
# Medido en esta CPU (sin GPU), costo por frase: tiny ~1.5s | base ~3s | small ~9s.
# 'small' NO sigue el ritmo en tiempo real aquí: úsalo solo si aceptas mucho retraso.
MODELOS = ["tiny", "base", "small"]


@dataclass
class Configuracion:
    # --- Reunión ---
    nombre_reunion: str = "Reunión sin título"
    idioma: str | None = "es"

    # --- Motor de transcripción (faster-whisper) ---
    # 'base' es el punto óptimo en esta CPU: ~3s/frase y sigue el ritmo en vivo.
    modelo: str = "base"
    device: str = "cpu"          # tu equipo no tiene CUDA: CPU.
    compute_type: str = "int8"   # int8 = rápido y ligero en CPU.
    cpu_threads: int = 4         # óptimo medido (1 hilo por núcleo físico).

    # --- Audio ---
    samplerate: int = 16000      # Whisper trabaja a 16 kHz.
    block_ms: int = 100          # tamaño de bloque de lectura.

    # --- Detección de voz (VAD por energía) ---
    silencio_corte_ms: int = 600   # silencio que cierra un segmento.
    max_segmento_s: float = 8.0    # corte forzado para acotar latencia (clave para tiempo real).
    umbral_voz: float = 0.012      # RMS mínimo base para considerar voz.
    min_segmento_s: float = 0.35   # descarta ruiditos demasiado cortos.

    # --- Dispositivos (None = el predeterminado del sistema) ---
    nombre_mic: str | None = None
    nombre_altavoz: str | None = None

    # --- ¿Usas audífonos? ---
    # True  -> captura micrófono (Yo) + loopback (Participantes): separación limpia.
    # False -> SOLO loopback (Participantes). Se desactiva el micrófono para que NO
    #          capte el eco de la reunión por los parlantes. Tu voz NO se transcribe.
    audifonos: bool = True

    # --- Salida ---
    carpeta_salida: str = "transcripciones"
