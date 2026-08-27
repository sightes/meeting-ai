# Notekeeper — Guía completa

CLI local para grabar reuniones, transcribirlas, consultarlas con IA y generar tareas Jira.

## Índice

1. [Instalación](#instalación)
2. [Captura de audio (mic, sistema o ambos)](#captura-de-audio)
3. [Grabar](#grabar)
4. [Transcribir](#transcribir)
5. [Consultar y buscar](#consultar-y-buscar)
6. [Resumen + tareas Jira](#resumen--tareas-jira)
7. [Configuración (.env)](#configuración-env)
8. [Estructura de datos](#estructura-de-datos)
9. [Solución de problemas](#solución-de-problemas)

---

## Instalación

```bash
cd meeting-ai
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

- Python 3.11+
- `ffmpeg` para soporte de MP3/M4A
- GPU recomendada para Whisper large-v3

---

## Captura de audio

En macOS el **micrófono físico jamás escucha el audio del sistema** (es hardware).
El audio de la computadora solo llega a través de dispositivos virtuales.

### Dispositivos típicos (después de instalar BlackHole)

| Dispositivo | Rol |
|---|---|
| `USB Microphone` | Tu voz (físico) |
| `BlackHole 2ch` | Cable virtual: recibe lo que sale por "notekeeper out" |
| `notekeeper out` | Multi-salida = Bocinas + BlackHole |
| `notekeeper in` | Agregado (mic + sistema) — opcional |

### Ruta del audio

1. Instala el driver virtual **BlackHole** (https://existential.audio/blackhole/).
2. En **Audio MIDI Setup** crea la multi-salida **"notekeeper out"** con
   `Bocinas + BlackHole 2ch`, todo a **48 kHz**.
3. En la app de la reunión (Zoom/Meet/Teams) configura la **salida** como
   **"notekeeper out"**: así el sonido va a tus oídos Y a BlackHole.
4. Graba con los comandos de abajo eligiendo la entrada correcta.

### ¿Qué entrada usar?

Modo de grabación                  | Entrada                       | Resultado
-----------------------------------|-------------------------------|----------------------------------
Micrófono físico                   | `-d 5` (USB Microphone)       | Solo tu voz
Solo audio del sistema             | `-d 10` (BlackHole 2ch)       | Solo la reunión/otros
Reunión completa (recomendado)     | `-m --mic 5`                  | Tu voz + audio del sistema (mezclado)

---

## Grabar

```bash
python -m notekeeper rec                  # Grabar con settings por defecto
python -m notekeeper rec -l               # Listar dispositivos de audio
python -m notekeeper rec -d 10            # Solo audio del sistema (BlackHole)
python -m notekeeper rec -m               # Reunión completa: mic + sistema mezclados
python -m notekeeper rec -m --mic 5       # Elegir el micrófono de la mezcla
python -m notekeeper rec -t 60            # Grabar 60 segundos
python -m notekeeper rec -o reunion       # Guardar en sesión "reunion"
```

Al terminar imprime los niveles por canal. Si está en silencio, revísalo en
[Solución de problemas](#solución-de-problemas).

---

## Transcribir

```bash
python -m notekeeper transcript                  # Transcribir todos los pendientes
python -m notekeeper transcript -s 2025-08-26    # Transcribir sesión específica
```

Usa faster-whisper (`WHISPER_MODEL`, por defecto `large-v3`). Detecta idioma
automáticamente y guarda `transcript.txt` + `segments.json` (con timestamps).

---

## Consultar y buscar

```bash
python -m notekeeper list                                      # Listar grabaciones
python -m notekeeper show                                      # Mostrar la más reciente
python -m notekeeper show 2025-08-26                           # Sesión específica
python -m notekeeper search "tareas pendientes"                # Buscar texto
python -m notekeeper search "staging" -n 10                    # Más resultados

# Chat con IA sobre tus transcripciones (RAG + LLM)
# Consulta las últimas 10 reuniones, indexadas por fecha
python -m notekeeper skill "qué tareas quedaron pendientes"
python -m notekeeper skill "qué se decidió sobre staging"
python -m notekeeper skill "quién quedó a cargo del backup"
python -m notekeeper skill -n 5 "tu pregunta"     # solo las últimas 5 reuniones
```

Requiere `LLM_API_KEY` en `.env` (OpenRouter: https://openrouter.ai/keys).
Sin key, `skill` devuelve el contexto relevante pero sin respuesta de IA.

---

## Resumen + tareas Jira

```bash
python -m notekeeper jira                  # Últimas 10 reuniones transcritas
python -m notekeeper jira -n 3             # Especificar cuántas reuniones
python -m notekeeper jira 2026-08-27       # Una sesión específica
```

Genera en la carpeta de la sesión más reciente:

- `meeting_summary.txt` — resumen de actividades y decisiones
- `tasks.json` — lista estructurada de tareas
- `jira_tasks.csv` — **importable a Jira** (Issue → Import issues from CSV)

Cada tarea incluye: **title**, **description** (con criterio de aceptación),
**issue_type** (Task/Story/Bug), **priority** (High/Medium/Low),
**story_points** (1/2/3/5/8 = tamaño), **eta** (AAAA-MM-DD), **assignee** y
**session** (la reunión de origen, para agrupar por fecha).

---

## Configuración (.env)

Crea `.env` (ya está en `.gitignore`):

```env
# Transcripción
WHISPER_MODEL=large-v3
WHISPER_DEVICE=auto
WHISPER_COMPUTE_TYPE=int8

# LLM via OpenRouter (para skill y jira)
LLM_MODEL=anthropic/claude-sonnet-4
LLM_API_KEY=sk-or-tu-key-aqui
LLM_BASE_URL=https://openrouter.ai/api/v1

# Datos
NOTEKEEPER_DATA=recordings

# Captura de audio (opcional)
NOTEKEEPER_SYSTEM_DEVICE=BlackHole 2ch
NOTEKEEPER_MIC_DEVICE=
```

---

## Estructura de datos

```
recordings/
├── 2025-08-26_14-30-00/
│   ├── recording.wav        # audio capturado
│   ├── transcript.txt       # transcripción completa
│   ├── segments.json        # segmentos con timestamps
│   ├── metadata.json        # fecha, duración, fuente, etc.
│   ├── meeting_summary.txt  # resumen (cmd jira)
│   ├── tasks.json           # tareas Jira (cmd jira)
│   └── jira_tasks.csv       # importable a Jira (cmd jira)
```

---

## Solución de problemas

| Síntoma | Causa / Solución |
|---|---|
| Grabas pero **no capturas el audio de la reunión** | La app debe emitir por la **multi-salida "notekeeper out"**, no por sus Bocinas/Auris propios. |
| Grabas tu voz pero **no el sistema** | Estás grabando del mic físico. Usa `-d 10` (BlackHole) o `-m` (mezcla). |
| Tos los computadores en silencio | Revisa en Audio MIDI Setup que **todos** los dispositivos estén a **48 kHz** (bloc de auto favorito de los problemas de BlackHole). |
| El agregado **"notekeeper in"** no captura el sistema | Los agregados con BlackHole son frágiles. Usa `-m` (mezcla en código) que no depende de él. |
| `skill` / `jira` dicen "No hay LLM_API_KEY" | Pega tu key en `.env`. |
| La transcripción tarda mucho en CPU | Baja a `WHISPER_MODEL=small` o `base` en `.env`. |