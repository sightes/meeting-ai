# Notekeeper

> **Local CLI for recording, transcribing, and analyzing meetings with AI.** Turn audio recordings into transcripts with speaker diarization, semantic search, and actionable summaries — all from your terminal.

Local CLI for processing recorded meetings: record, transcribe, segment by context (company/project), diarize speakers, search (text and semantic), and query with AI — including an **interactive console chat**.

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-Not%20specified-lightgrey)
![CLI](https://img.shields.io/badge/CLI-notekeeper-4B8BBE)

> Full guide (system audio capture, commands, configuration, and troubleshooting): **[GUIA.md](GUIA.md)**

## Features

- 🎙️ **Record** meetings (microphone + system audio).
- 📝 **Transcribe** with Whisper (faster-whisper).
- 🗂️ **Segment by context**: tag each meeting with company/project (`--tags`) and filter queries by context.
- 👥 **Diarize** speakers (pyannote).
- 🔎 **Search** by text and **semantic search** (embeddings, local or OpenRouter).
- 💬 **Query with AI**: `skill` command (single question) and `./ask` (**interactive chat** with memory).
- 📋 **Jira tasks**: summary + importable `jira_tasks.csv`.

## Installation

```bash
cd meeting-ai
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

To install as a `notekeeper` command:
```bash
pip install -e .
```

## Usage

### Record audio
```bash
python -m notekeeper rec              # Record with default settings
python -m notekeeper rec -l           # List audio devices
python -m notekeeper rec -d 10        # Use specific device (10 = BlackHole 2ch)
python -m notekeeper rec -m           # Full meeting: microphone + system audio mixed
python -m notekeeper rec -m --mic 5   # Choose the microphone for mixing
python -m notekeeper rec -t 60        # Record for 60 seconds
python -m notekeeper rec -o meeting   # Save to session "meeting"
python -m notekeeper rec -m --tags acme   # Assign context (company/project) to the meeting
```

### Segment by context (companies/projects)

Each recording can carry one or more **tags** (contexts) saved in `metadata.json`. This lets you split your knowledge base by company, project, client, etc.

```bash
./grabar --tags acme                      # assign context when recording
python -m notekeeper tag <session> acme   # tag/re-tag a session
python -m notekeeper list --tag acme      # list only sessions with that context
```

To query only meetings from a specific context, pass the tag (without `#`, as bash interprets `#` as a comment):

```bash
./ask acme                                # chat restricted to acme meetings
python -m notekeeper skill "what tasks" --tag acme
python -m notekeeper search "staging" --tag acme
python -m notekeeper jira --tags acme
```

Tags work with both context search and embeddings (semantic search), and a single meeting can belong to multiple contexts.

### Interactive chat (terminal-based, opencode-style)

`./ask` opens a terminal chat where you can ask multiple follow-up questions about your meetings, maintaining conversation context:

```bash
./ask                     # chat about all your meetings
./ask acme                # chat restricted to the acme context
./ask -e                  # chat with semantic search via embeddings
```

Type `salir`, `exit` or `quit` (or Ctrl-C) to quit.

### Transcribe
```bash
python -m notekeeper transcript                # Transcribe all pending
python -m notekeeper transcript -s 2025-08-26  # Transcribe specific session
```

### View transcriptions
```bash
python -m notekeeper list              # List all recordings
python -m notekeeper show              # Show the most recent
python -m notekeeper show 2025-08-26   # Show specific session
```

### Search
```bash
python -m notekeeper search "pending tasks"
python -m notekeeper search "staging" -n 10
```

### Ask with AI (RAG)
```bash
python -m notekeeper skill what tasks are pending
python -m notekeeper skill what was decided about staging
python -m notekeeper skill who is in charge of the backup
```

### Summary + Jira tasks
```bash
python -m notekeeper jira                  # Most recent session
python -m notekeeper jira 2025-08-26       # Specific session
```
Generates `meeting_summary.txt`, `tasks.json`, and `jira_tasks.csv` (importable to Jira) with title, description, type, priority, story points, and ETA per task.

## Data structure

```
recordings/
├── 2025-08-26_14-30-00/
│   ├── recording.wav
│   ├── transcript.txt
│   ├── segments.json
│   └── metadata.json   # tags (contexts) are stored here
├── 2025-08-25_10-00-00/
│   ├── meeting.mp3
│   ├── transcript.txt
│   ├── segments.json
│   └── metadata.json
```

Example `metadata.json` with tags:

```json
{
  "recorded_at": "2025-08-26T14:30:00",
  "duration": 1041.66,
  "tags": ["acme", "migration-project"]
}
```

## Configuration (.env)

```env
# Transcription
WHISPER_MODEL=large-v3
WHISPER_DEVICE=auto
WHISPER_COMPUTE_TYPE=int8

# LLM via OpenRouter (for skill)
LLM_MODEL=anthropic/claude-sonnet-4
LLM_API_KEY=sk-or-...
LLM_BASE_URL=https://openrouter.ai/api/v1

# Data
NOTEKEEPER_DATA=recordings
```

## Requirements

- Python 3.11+
- ffmpeg (for MP3/M4A support)
- GPU recommended for Whisper large-v3

## Changelog

All version changes are documented in **[CHANGELOG.md](CHANGELOG.md)**.

## Contributing

1. Fork the repository (https://github.com/sightes/meeting-ai).
2. Create a branch (`git checkout -b feature/my-change`).
3. Commit your changes and open a pull request.

To report bugs or suggest improvements, open an issue on
[GitHub Issues](https://github.com/sightes/meeting-ai/issues).

## License

No explicit license: usage is limited to the `sightes/meeting-ai` repository.
Contact the author before redistributing.
