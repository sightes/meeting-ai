# Notekeeper

CLI local para procesar reuniones grabadas.

> Guía completa (captura de audio del sistema, comandos, configuración y troubleshooting): **[GUIA.md](GUIA.md)**

## Instalación

```bash
cd meeting-ai
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Para usar como comando `notekeeper`:
```bash
pip install -e .
```

## Uso

### Grabar audio
```bash
python -m notekeeper rec              # Grabar con settings por defecto
python -m notekeeper rec -l           # Listar dispositivos de audio
python -m notekeeper rec -d 10        # Usar dispositivo específico (10 = BlackHole 2ch)
python -m notekeeper rec -m           # Reunión completa: micrófono + audio de sistema mezclados
python -m notekeeper rec -m --mic 5   # Elegir el micrófono de la mezcla
python -m notekeeper rec -t 60        # Grabar 60 segundos
python -m notekeeper rec -o reunion   # Guardar en sesión "reunion"
```

### Transcribir
```bash
python -m notekeeper transcript                # Transcribir todos los pendientes
python -m notekeeper transcript -s 2025-08-26  # Transcribir sesión específica
```

### Ver transcripciones
```bash
python -m notekeeper list              # Listar todas las grabaciones
python -m notekeeper show              # Mostrar la más reciente
python -m notekeeper show 2025-08-26   # Mostrar sesión específica
```

### Buscar
```bash
python -m notekeeper search "tareas pendientes"
python -m notekeeper search "staging" -n 10
```

### Preguntar con IA (RAG)
```bash
python -m notekeeper skill qué tareas quedaron pendientes
python -m notekeeper skill qué se decidió sobre staging
python -m notekeeper skill quién quedó a cargo del backup
```

### Resumen + tareas Jira
```bash
python -m notekeeper jira                  # Sesión más reciente
python -m notekeeper jira 2025-08-26       # Sesión específica
```
Genera `meeting_summary.txt`, `tasks.json` y `jira_tasks.csv` (importable a Jira) con
titulo, descripción, tipo, prioridad, story points y ETA por tarea.

## Estructura de datos

```
recordings/
├── 2025-08-26_14-30-00/
│   ├── recording.wav
│   ├── transcript.txt
│   ├── segments.json
│   └── metadata.json
├── 2025-08-25_10-00-00/
│   ├── reunion.mp3
│   ├── transcript.txt
│   ├── segments.json
│   └── metadata.json
```

## Configuración (.env)

```env
# Transcripción
WHISPER_MODEL=large-v3
WHISPER_DEVICE=auto
WHISPER_COMPUTE_TYPE=int8

# LLM via OpenRouter (para skill)
LLM_MODEL=anthropic/claude-sonnet-4
LLM_API_KEY=sk-or-...
LLM_BASE_URL=https://openrouter.ai/api/v1

# Datos
NOTEKEEPER_DATA=recordings
```

## Requisitos

- Python 3.11+
- ffmpeg (para soporte MP3/M4A)
- GPU recomendada para Whisper large-v3
