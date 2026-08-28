# Notekeeper

CLI local para procesar reuniones grabadas: graba, transcribe, segmenta por
contexto (empresa/proyecto), diariza hablantes, busca (texto y semántica) y
consulta con IA —incluido un **chat interactivo en consola**.

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-Not%20specified-lightgrey)
![CLI](https://img.shields.io/badge/CLI-notekeeper-4B8BBE)

> Guía completa (captura de audio del sistema, comandos, configuración y troubleshooting): **[GUIA.md](GUIA.md)**

## Características

- 🎙️ **Grabar** reuniones (micrófono + sistema).
- 📝 **Transcribir** con Whisper (faster-whisper).
- 🗂️ **Segmentar por contexto**: etiqueta cada reunión con empresa/proyecto
  (`--tags`) y filtra consultas por contexto.
- 👥 **Diarizar** hablantes (pyannote).
- 🔎 **Buscar** por texto y **búsqueda semántica** (embeddings, local u OpenRouter).
- 💬 **Consultar con IA**: comando `skill` (una pregunta) y `./ask` (**chat interactivo** con memoria).
- 📋 **Tareas Jira**: resumen + `jira_tasks.csv` importable.

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
python -m notekeeper rec -m --tags scotiabank   # Asignar contexto (empresa/proyecto) a la reunión
```

### Segmentar por contexto (empresas/proyectos)

Cada grabación puede llevar uno o más **tags** (contextos) guardados en
`metadata.json`. Así puedes separar tu base de conocimiento por empresa,
proyecto, cliente, etc.

```bash
./grabar --tags scotiabank                 # asignar contexto al grabar
python -m notekeeper tag <sesion> scotiabank   # etiquetar/re-etiquetar una sesión
python -m notekeeper list --tag scotiabank     # listar solo sesiones de ese contexto
```

Para consultar solo las reuniones de un contexto, pasa el tag (sin `#`, el
`#` lo interpreta bash como comentario):

```bash
./ask scotiabank                          # chat restringido a reuniones de Scotiabank
python -m notekeeper skill "qué tareas" --tag scotiabank
python -m notekeeper search "staging" --tag scotiabank
python -m notekeeper jira --tags scotiabank
```

El tag funciona tanto con búsqueda por contexto como con embeddings
(búsqueda semántica), y una reunión puede pertenecer a varios contextos a la vez.

### Chat interactivo (tipo opencode, en consola)

`./ask` abre un chat en la terminal donde puedes hacer varias preguntas
seguidas sobre tus reuniones, manteniendo el contexto de la conversación:

```bash
./ask                     # chat sobre todas tus reuniones
./ask scotiabank          # chat restringido al contexto scotiabank
./ask -e                  # chat con búsqueda semántica por embeddings
```

Escribe `salir`, `exit` o `quit` (o Ctrl-C) para terminar.

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
│   └── metadata.json   # aquí se guardan los "tags" (contextos)
├── 2025-08-25_10-00-00/
│   ├── reunion.mp3
│   ├── transcript.txt
│   ├── segments.json
│   └── metadata.json
```

Ejemplo de `metadata.json` con tags:

```json
{
  "recorded_at": "2025-08-26T14:30:00",
  "duration": 1041.66,
  "tags": ["scotiabank", "proyecto-migracion"]
}
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

## Changelog

Todos los cambios por versión se documentan en **[CHANGELOG.md](CHANGELOG.md)**.

## Contribución

1. Haz *fork* del repositorio (https://github.com/sightes/meeting-ai).
2. Crea una rama (`git checkout -b feature/mi-cambio`).
3. Haz commit de tus cambios y abre un *pull request*.

Para reportar errores o sugerir mejoras, abre un *issue* en
[GitHub Issues](https://github.com/sightes/meeting-ai/issues).

## Licencia

Sin licencia explícita: el uso queda limitado al repositorio de `sightes/meeting-ai`.
Contacta al autor antes de redistribuir.

