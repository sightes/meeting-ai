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
- 🔄 **Export to GitHub Projects**: creates issues and adds them to a v2 board, with fields (Status/Priority/Size/Estimate/dates) and context labels.
- 📄 **Markdown summaries**: generates `summaries/[tag][date][topic].md` for each meeting.

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

### Speaker diarization

Labels each transcript segment with its speaker (`SPEAKER_00`, `SPEAKER_01`...) using pyannote, so the LLM can identify who took on each task:

```bash
python -m notekeeper diarize                 # all transcribed sessions
python -m notekeeper diarize 2025-08-26      # one session
python -m notekeeper diarize --tag acme      # only sessions with a tag
python -m notekeeper diarize -n              # also prompt for each speaker's real name
python -m notekeeper diarize -r              # diarize + rebuild the embedding index
python -m notekeeper diarize -f              # re-diarize even if already done
```

Requires `HF_TOKEN` in `.env` with access to the model (click "Agree and access" at
[pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)).
Inference is 100% local (CPU by default; GPU/MPS auto-detected, or set
`DIARIZATION_DEVICE=cpu|cuda|mps`).

With `-n` you assign real names (saved in `metadata.json` as `speakers`), e.g.
`SPEAKER_00` → `Jane`. Without `-n`, speakers are auto-labeled `Locutor 1`,
`Locutor 2`, etc. Speaker names are prepended to fragments in the embedding
index and LLM context — rebuild the index afterwards (`embed-index --rebuild`
or `diarize -r`) so they reach semantic search and Jira task assignees.

### Semantic search (embeddings)

By default, `skill` dumps the last N meetings into the LLM. For pointed
questions ("what was agreed about X?"), **semantic search** sends only the
relevant fragments, so it scales to hundreds of meetings without running out
of context.

```bash
# 1) Index the transcripts (once; re-run with --rebuild after new transcriptions)
python -m notekeeper embed-index
python -m notekeeper embed-index --rebuild     # force re-index
python -m notekeeper embed-index -l            # show index status

# 2) Query using the index
python -m notekeeper skill -s "what was agreed about staging"
python -m notekeeper jira -e                   # tasks from relevant fragments
./ask -e                                       # interactive chat with embeddings
```

Providers (in `.env`): `EMBEDDING_PROVIDER=local` (default, sentence-transformers,
offline) or `openrouter` (uses `LLM_API_KEY`). Quality tuning via
`EMBEDDING_CHUNK_CHARS`, `EMBEDDING_MIN_SIM` and `EMBEDDING_REL_SIM` — see
[GUIA.md](GUIA.md) for details.

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

### Export to GitHub Projects
If you configure `GITHUB_REPO` and `GITHUB_PROJECT_URL` (see `.env`), each
meeting's tasks are synced automatically to a **GitHub Projects v2** board:
it creates new issues (deduplicated against existing ones via LLM), adds them
to the board, and fills in Status/Priority/Size/Estimate/dates.

```bash
python -m notekeeper jira                   # summary + tasks + export to board
python -m notekeeper backfill               # fill fields of tasks already on the board
python -m notekeeper describe-fields        # generate descriptions for board columns
```

> Note: `resume` and `backfill` do not create new tasks. Tasks are exported to
> the board when running `jira`. `backfill` only fills in fields of tasks already
> on the board.

### Markdown summaries
`./resume` converts each summarized meeting (with `meeting_summary.txt`) into a
`summaries/[tag][date][topic].md` file (replaced if it already exists). It does
not touch the GitHub board; it only generates local summaries and syncs them to
the project repository (`project-tracking`).

```bash
./resume                                   # MD summaries for all meetings + sync
python -m notekeeper resume
```

### Export to macOS Notes & Reminders
Optional: create an Apple Notes note with the meeting summary and a
Reminder per task.

```bash
python -m notekeeper export-mac --dry-run           # preview (no iCloud changes)
python -m notekeeper export-mac                     # create notes + reminders
python -m notekeeper export-mac 2026-08-27          # only one session
python -m notekeeper export-mac --tag scotiabank    # only sessions with a tag
```
> The first real run asks for Automation permission for your terminal to
> control Notes and Reminders (System Settings → Privacy). Use `--dry-run`
> first to preview exactly what would be created.

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

# Embeddings (semantic search)
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2

# Speaker diarization (optional, for `diarize`)
# HF_TOKEN=hf_xxxx
# DIARIZATION_MODEL=pyannote/speaker-diarization-community-1
# DIARIZATION_DEVICE=auto

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
