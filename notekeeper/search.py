"""Búsqueda simple sobre transcripciones."""
import json
from pathlib import Path

from notekeeper.storage import list_sessions, get_transcript_text, load_metadata, get_tags


def search_transcripts(query: str, limit: int = 5, tags: list[str] | None = None) -> list[dict]:
    """Búsqueda por palabras clave con contexto.

    Si ``tags`` se indica, filtra solo sesiones con alguno de esos tags.
    Devuelve los fragmentos más relevantes con información de la sesión.
    """
    results = []
    query_lower = query.lower()
    query_words = query_lower.split()

    if tags:
        tag_set = {t.lower() for t in tags}
        sessions = [s for s in list_sessions() if tag_set.intersection(get_tags(s))]
    else:
        sessions = list_sessions()

    for session in sessions:
        text = get_transcript_text(session)
        if not text:
            continue

        meta = load_metadata(session)
        text_lower = text.lower()

        # Score: contar palabras de la query que aparecen
        score = sum(1 for w in query_words if w in text_lower)
        if score == 0:
            continue

        # Buscar fragmentos con contexto
        segments = _load_segments(session)
        fragments = _extract_fragments(segments, query_words)

        results.append({
            "session": session.name,
            "date": meta.get("recorded_at", session.name),
            "duration": meta.get("duration"),
            "score": score,
            "fragments": fragments,
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]


def _load_segments(session: Path) -> list[dict]:
    seg_path = session / "segments.json"
    if seg_path.exists():
        return json.loads(seg_path.read_text(encoding="utf-8"))
    return []


def _extract_fragments(segments: list[dict], query_words: list[str]) -> list[dict]:
    """Encuentra segmentos relevantes y su contexto."""
    fragments = []
    for i, seg in enumerate(segments):
        text_lower = seg["text"].lower()
        if any(w in text_lower for w in query_words):
            # Contexto: 1 segmento antes y después
            context_start = max(0, i - 1)
            context_end = min(len(segments), i + 2)
            context_segs = segments[context_start:context_end]

            fragment_text = " ".join(s["text"] for s in context_segs)
            fragments.append({
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"],
                "context": fragment_text,
            })

    return fragments


def format_results(results: list[dict], query: str) -> str:
    """Formatea resultados de búsqueda."""
    if not results:
        return f'No se encontraron resultados para: "{query}"'

    lines = [f'Resultados para: "{query}"\n']

    for r in results:
        dur = f"{r['duration']:.0f}s" if r.get("duration") else ""
        lines.append(f"--- {r['session']} ({r['date']}) {dur} ---")

        for frag in r["fragments"]:
            ts = _format_time(frag["start"])
            lines.append(f"  [{ts}] {frag['text']}")

        lines.append("")

    return "\n".join(lines)


def format_full_transcript(session: Path) -> str:
    """Muestra la transcripción completa de una sesión."""
    text = get_transcript_text(session)
    if not text:
        return f"No hay transcripción en {session.name}"

    meta = load_metadata(session)
    header = f"Sesión: {session.name}\n"
    if meta.get("recorded_at"):
        header += f"Fecha: {meta['recorded_at']}\n"
    if meta.get("duration"):
        header += f"Duración: {meta['duration']:.0f}s\n"

    return header + "\n" + text


def _format_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
