"""Modelos de dominio: las entidades que viajan por el sistema."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Hablante(str, Enum):
    """Quién habla. En el MVP se determina por la FUENTE de audio, no por la voz."""

    YO = "Yo"                      # micrófono = siempre tú
    PARTICIPANTES = "Participantes"  # audio del sistema (loopback) = los demás


@dataclass
class Segmento:
    """Un fragmento de habla ya transcrito, ubicado en la línea de tiempo."""

    hablante: Hablante
    inicio: float  # segundos desde el inicio de la reunión
    fin: float
    texto: str = ""
