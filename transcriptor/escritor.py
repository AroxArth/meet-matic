"""Escritura del .md: un log en vivo (orden de llegada) que al detener se
reescribe ordenado cronológicamente. El formato está pensado para que una IA
lo entienda sin esfuerzo: encabezado con metadatos + turnos con timestamp y
hablante.
"""

from __future__ import annotations

import os
import re
from datetime import datetime

from transcriptor.config import Configuracion
from transcriptor.modelos import Segmento

_NOMBRE_IDIOMA = {"es": "Español", "en": "English", None: "Auto"}


def _hms(segundos: float) -> str:
    s = int(segundos)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _slug(texto: str) -> str:
    limpio = re.sub(r"[^\w\s-]", "", texto, flags=re.UNICODE).strip()
    return re.sub(r"\s+", "_", limpio) or "reunion"


class EscritorMarkdown:
    def __init__(self, cfg: Configuracion, inicio_dt: datetime):
        self.cfg = cfg
        self.inicio_dt = inicio_dt
        self.segmentos: list[Segmento] = []

        os.makedirs(cfg.carpeta_salida, exist_ok=True)
        # Nombre de la reunión primero, fecha después: "PruebasUnitariasSISAC_2026-06-24.md"
        base = f"{_slug(cfg.nombre_reunion)}_{inicio_dt.strftime('%Y-%m-%d')}"
        ruta = os.path.join(cfg.carpeta_salida, f"{base}.md")
        # Si ya hay una reunión con ese nombre el mismo día, añade la hora para no sobrescribir.
        if os.path.exists(ruta):
            ruta = os.path.join(cfg.carpeta_salida, f"{base}_{inicio_dt.strftime('%H%M%S')}.md")
        self.ruta = ruta

        with open(self.ruta, "w", encoding="utf-8") as f:
            self._cabecera(f)
            f.write("## Transcripción\n\n")

    def _cabecera(self, f, duracion: str | None = None) -> None:
        f.write(f"# {self.cfg.nombre_reunion}\n\n")
        f.write(f"- **Fecha:** {self.inicio_dt.strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"- **Idioma:** {_NOMBRE_IDIOMA.get(self.cfg.idioma, self.cfg.idioma)}\n")
        f.write(f"- **Modelo:** faster-whisper `{self.cfg.modelo}`\n")
        if duracion:
            f.write(f"- **Duración:** {duracion}\n")
        f.write("\n---\n\n")

    @staticmethod
    def _linea(s: Segmento) -> str:
        return f"**[{_hms(s.inicio)}] {s.hablante.value}:** {s.texto}\n\n"

    def agregar(self, segmento: Segmento) -> None:
        """Append en vivo, en orden de finalización."""
        self.segmentos.append(segmento)
        with open(self.ruta, "a", encoding="utf-8") as f:
            f.write(self._linea(segmento))

    def finalizar(self, fin_dt: datetime | None = None) -> str:
        """Reescribe el archivo ordenado por tiempo de inicio (versión limpia)."""
        self.segmentos.sort(key=lambda s: s.inicio)
        duracion = _hms((fin_dt - self.inicio_dt).total_seconds()) if fin_dt else None
        with open(self.ruta, "w", encoding="utf-8") as f:
            self._cabecera(f, duracion)
            f.write("## Transcripción\n\n")
            for s in self.segmentos:
                f.write(self._linea(s))
        return self.ruta
