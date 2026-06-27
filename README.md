# Transcriptor de Reuniones

Alternativa **en texto** a grabar la pantalla: escucha tu **micrófono** y el
**audio de la reunión** (lo que suena por tus altavoces) y los transcribe en
tiempo real a un archivo **Markdown** listo para pasárselo a una IA.

Todo corre **local** (faster-whisper). El audio NO sale de tu PC.

## Cómo funciona la separación de hablantes

En esta versión los hablantes se distinguen por **fuente de audio**, no por la
voz:

- **`Yo`** → tu micrófono.
- **`Participantes`** → el audio del sistema (los demás en la reunión).

Esto es 100% confiable y en tiempo real. Separar a cada participante por su voz
(Persona 2 vs Persona 3) es una mejora futura (diarización *offline* con
`pyannote`).

> 💡 **¿Audífonos o parlantes?** La app tiene un interruptor **🎧 Tengo
> audífonos puestos**:
>
> - **Activado (audífonos):** captura tu micrófono (`Yo`) **y** la reunión
>   (`Participantes`) por separado. Separación limpia.
> - **Desactivado (parlantes):** captura **solo la reunión**. Tu micrófono se
>   desactiva para que no capte el eco de los parlantes. **Tu voz NO queda en el
>   `.md`** — es el precio de evitar la contaminación de canales.

## Requisitos

- Windows 10/11
- Python 3.11+ (probado en 3.14)
- Conexión a internet **la primera vez** (para descargar el modelo). Después
  funciona sin conexión.

## Instalación

> ⚠️ **El entorno virtual (`.venv`) NO es portable.** No copies la carpeta
> `.venv` de otra máquina: guarda rutas absolutas al Python con el que se creó
> y se rompe al moverla. Siempre se **recrea** desde `requirements.txt`.

Desde esta carpeta, en PowerShell:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Si clonaste el repo en una máquina nueva, esos tres comandos son todo lo que
necesitas: el `.venv` no viaja en el repo, se reconstruye en cada equipo.

## Uso

Doble clic en **`iniciar.bat`**, o:

```powershell
.\.venv\Scripts\python.exe -m transcriptor
```

1. Escribe el **nombre de la reunión**.
2. Elige **idioma** (Español por defecto, English, o Auto).
3. Activa o desactiva **🎧 Tengo audífonos puestos** (ver nota arriba). El texto
   bajo el interruptor te muestra qué se va a capturar.
4. (Opcional) elige micrófono y altavoz; déjalos en *Automático* si no sabes.
5. **▶ Iniciar**. Habla / pon la reunión.
6. **⏹ Detener** al terminar.

El `.md` se guarda en la carpeta `transcripciones/`.

## Ajustes (transcriptor/config.py)

| Parámetro | Para qué | Default |
|---|---|---|
| `modelo` | Calidad vs velocidad: `tiny`/`base`/`small` | `base` |
| `cpu_threads` | Hilos de CPU para transcribir (óptimo: nº de núcleos físicos) | `4` |
| `umbral_voz` | Sensibilidad del detector de voz (súbelo si capta ruido, bájalo si se come palabras) | `0.012` |
| `silencio_corte_ms` | Cuánto silencio cierra una frase | `600` |
| `max_segmento_s` | Corte máximo de un bloque (clave para la latencia en monólogos) | `8` |

### Velocidad de los modelos (medido en CPU sin GPU)

Whisper procesa internamente en ventanas de 30s, así que el costo por frase es
**casi fijo** sin importar lo corta que sea:

| Modelo | Costo por frase | ¿Tiempo real en esta CPU? |
|---|---|---|
| `tiny` | ~1.5s | Sí, vuela (menos preciso) |
| `base` | ~3s | **Sí — recomendado** |
| `small` | ~9s | No: acumula 20s+ de retraso |

**Tu equipo no tiene GPU NVIDIA**, por eso `small`/`medium` no rinden en vivo.
Para máxima precisión sin retraso necesitarías GPU o una API en la nube — o
transcribir el audio *después* de la reunión (sin límite de latencia).

## Estructura

```
transcriptor/
  config.py        # parámetros de la sesión
  modelos.py       # entidades de dominio (Hablante, Segmento)
  audio.py         # captura mic + loopback + VAD por energía
  transcripcion.py # faster-whisper + hilo trabajador
  escritor.py      # genera el .md
  grabador.py      # orquestador (une todo)
  ui.py            # interfaz CustomTkinter
```
