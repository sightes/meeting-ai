"""Construcción de contexto de reuniones (indexado por fecha) para llamadas LLM."""
import json
from pathlib import Path

from notekeeper.storage import list_sessions, get_transcript_text, load_metadata


def _fmt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _session_lines(session: Path, max_segments: int) -> list[str]:
    seg_path = session / "segments.json"
    if seg_path.exists():
        segments = json.loads(seg_path.read_text(encoding="utf-8"))
        lines = [f"[{_fmt_time(seg['start'])}] {seg['text']}" for seg in segments[:max_segments]]
        if len(segments) > max_segments:
            lines.append(f"... (+{len(segments) - max_segments} segmentos omitidos)")
        return lines
    text = get_transcript_text(session)
    return [text] if text else []


def _session_block(session: Path, max_segments: int) -> str:
    meta = load_metadata(session)
    dur = meta.get("duration")
    dur_str = f"{dur:.0f}s" if isinstance(dur, (int, float)) else "?"
    lines = [f"### Reunión: {session.name} (fecha {meta.get('recorded_at', session.name)}, duración {dur_str})"]
    source = meta.get("source", "")
    if source:
        lines.append(f"Fuente: {source}")
    body = _session_lines(session, max_segments)
    if not body:
        lines.append("(sin transcripción)")
    else:
        lines.extend(body)
    return "\n".join(lines)


def meetings_context(limit: int = 10, max_segments: int = 60, max_chars: int | None = None) -> str:
    """Últimas `limit` reuniones (más reciente primero, indexadas por fecha)."""
    sessions = list_sessions()[:limit]
    text = "\n\n".join(_session_block(s, max_segments) for s in sessions)
    if max_chars and len(text) > max_chars:
        text = text[:max_chars] + "\n[contexto truncado por límite de tokens]"
    return text or "(no hay transcripciones)"


def session_context(session: Path, max_segments: int = 120) -> str:
    """Una sola sesión, indexada por fecha."""
    return _session_block(session, max_segments)