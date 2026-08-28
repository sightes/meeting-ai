import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(os.getenv("NOTEKEEPER_DATA", "recordings"))
NOTEKEEPER_SYSTEM_DEVICE = os.getenv("NOTEKEEPER_SYSTEM_DEVICE", "BlackHole 2ch")
NOTEKEEPER_MIC_DEVICE = os.getenv("NOTEKEEPER_MIC_DEVICE", "")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto")
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
LLM_MODEL = os.getenv("LLM_MODEL", "anthropic/claude-sonnet-4")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")

EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "local")
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
EMBEDDING_INDEX = Path(os.getenv("EMBEDDING_INDEX", "data/embeddings.json"))
EMBEDDING_TOP_K = int(os.getenv("EMBEDDING_TOP_K", "8"))

# Fusionar segmentos cortos del mismo hablante en chunks semánticos antes de embeddir
EMBEDDING_CHUNK_CHARS = int(os.getenv("EMBEDDING_CHUNK_CHARS", "300"))

# Filtros de similitud en la búsqueda (0 desactiva)
EMBEDDING_MIN_SIM = float(os.getenv("EMBEDDING_MIN_SIM", "0.0"))  # piso absoluto
EMBEDDING_REL_SIM = float(
    os.getenv("EMBEDDING_REL_SIM", "0.7")
)  # relativo al mejor resultado

# Modelo de embeddings vía OpenRouter (usado cuando EMBEDDING_PROVIDER=openrouter)
EMBEDDING_OPENROUTER_MODEL = os.getenv(
    "EMBEDDING_OPENROUTER_MODEL", "openai/text-embedding-3-small"
)

# Diarización de hablantes (opcional; requiere acceso al modelo de HuggingFace)
HF_TOKEN = os.getenv("HF_TOKEN", "")
DIARIZATION_MODEL = os.getenv(
    "DIARIZATION_MODEL", "pyannote/speaker-diarization-community-1"
)
DIARIZATION_DEVICE = os.getenv("DIARIZATION_DEVICE", "auto")  # auto | cpu | cuda | mps

AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".flac"}


def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
