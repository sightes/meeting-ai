"""Búsqueda semántica por embeddings sobre transcripciones.

Soporta dos proveedores configurables vía `.env`:
- ``EMBEDDING_PROVIDER=local``  (por defecto): sentence-transformers, sin red.
- ``EMBEDDING_PROVIDER=openrouter``: API de embeddings vía OpenRouter.
"""
import json
from pathlib import Path

from notekeeper.config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    EMBEDDING_PROVIDER,
    EMBEDDING_MODEL,
    EMBEDDING_INDEX,
    EMBEDDING_TOP_K,
    EMBEDDING_CHUNK_CHARS,
    EMBEDDING_MIN_SIM,
    EMBEDDING_REL_SIM,
    EMBEDDING_OPENROUTER_MODEL,
    DATA_DIR,
)
from notekeeper.storage import list_sessions


# --------------------------------------------------------------------------- #
# Carga de vectores (modelos pesados se cargan una sola vez)
# --------------------------------------------------------------------------- #
_model = None


def _get_local_model():
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise SystemExit(
                "Para embeddings locales instala: pip install sentence-transformers "
                "(o usa EMBEDDING_PROVIDER=openrouter en .env)"
            ) from exc
        print(f"Cargando modelo de embeddings local ({EMBEDDING_MODEL})...")
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def _get_openrouter_client():
    if not LLM_API_KEY:
        raise SystemExit("Falta LLM_API_KEY en .env para usar embeddings vía OpenRouter.")
    from openai import OpenAI

    return OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)


def embed(texts: list[str]) -> list[list[float]]:
    """Devuelve los vectores de los textos según el proveedor configurado."""
    if not texts:
        return []

    if EMBEDDING_PROVIDER == "openrouter":
        client = _get_openrouter_client()
        resp = client.embeddings.create(
            model=EMBEDDING_OPENROUTER_MODEL,
            input=texts,
            encoding_format="float",
        )
        # OpenRouter puede devolver list o dict
        data = resp.data
        if isinstance(data, dict):
            data = data.get("data", [])
        data = sorted(data, key=lambda d: d.index)
        return [d.embedding for d in data]

    model = _get_local_model()
    vecs = model.encode(
        texts, normalize_embeddings=True, show_progress_bar=False, batch_size=64
    )
    return vecs.tolist()


# --------------------------------------------------------------------------- #
# Índice persistente
# --------------------------------------------------------------------------- #
def _index_path() -> Path:
    EMBEDDING_INDEX.parent.mkdir(parents=True, exist_ok=True)
    return EMBEDDING_INDEX


def load_index() -> dict:
    p = _index_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"model": EMBEDDING_MODEL, "segments": []}


def save_index(index: dict):
    _index_path().write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")


def _segment_texts(session: Path) -> list[dict]:
    """Agrupa los segmentos de una sesión en chunks semánticos.

    Fusiona segmentos consecutivos del mismo hablante (o sin diarizar) hasta
    juntar ~EMBEDDING_CHUNK_CHARS caracteres, cortando ante silencios largos
    (>2 s) o cambio de hablante. Devuelve un item por chunk.
    """
    seg_path = session / "segments.json"
    if not seg_path.exists():
        return []
    try:
        segments = json.loads(seg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    from notekeeper.diarizer import speakers_map

    names = speakers_map(session)
    speakers = sorted({seg.get("speaker") for seg in segments if seg.get("speaker")})

    def _label(speaker):
        if not speaker:
            return None
        if speaker in names:
            return names[speaker]
        if speaker in speakers:
            return f"Locutor {speakers.index(speaker) + 1}"
        return None

    gap_max = 2.0  # segundos de silencio que separan chunks
    target = EMBEDDING_CHUNK_CHARS
    items = []

    buf: list[str] = []
    chars = 0
    start = end = 0.0
    spk = None

    def flush():
        nonlocal buf, chars, end
        if not buf:
            return
        text = " ".join(buf).strip()
        if len(text) >= 15:
            items.append(
                {
                    "session": session.name,
                    "start": start,
                    "end": end,
                    "text": text,
                    "speaker": spk,
                    "speaker_label": _label(spk),
                }
            )
        buf = []
        chars = 0

    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        speaker = seg.get("speaker")
        seg_start, seg_end = seg.get("start") or 0.0, seg.get("end") or 0.0
        gap = seg_start - end if buf else 0.0
        if (
            buf
            and (speaker != spk or gap > gap_max or chars + len(text) > target)
        ):
            flush()
        if not buf:
            start = seg_start
            spk = speaker
        buf.append(text)
        chars += len(text)
        end = seg_end

    flush()
    return items


def _embed_text(item: dict) -> str:
    """Texto que se vectoriza: prefija el nombre del hablante si está diarizado."""
    label = item.get("speaker_label")
    return f"{label}: {item['text']}" if label else item["text"]


def index_sessions(force: bool = False, verbose: bool = True) -> dict:
    """Indexa los segmentos de todas las sesiones y guarda el archivo."""
    index = load_index()
    if not force and index.get("segments"):
        if verbose:
            print(f"Índice existente ({len(index['segments'])} segmentos). Usa --rebuild para regenerar.")
        return index

    model = EMBEDDING_MODEL
    if EMBEDDING_PROVIDER == "openrouter":
        model = EMBEDDING_OPENROUTER_MODEL

    all_items = []
    for session in list_sessions():
        all_items.extend(_segment_texts(session))

    if not all_items:
        print("No hay transcripciones (segments.json) para indexar.")
        return index

    if verbose:
        print(f"Generando embeddings para {len(all_items)} segmentos ({EMBEDDING_PROVIDER})...")

    vectors = embed([_embed_text(it) for it in all_items])

    index = {
        "model": model,
        "provider": EMBEDDING_PROVIDER,
        "segments": [
            {**it, "vector": vec} for it, vec in zip(all_items, vectors)
        ],
    }
    save_index(index)
    if verbose:
        print(f"Índice guardado en {EMBEDDING_INDEX} ({len(index['segments'])} segmentos)")
    return index


# --------------------------------------------------------------------------- #
# Búsqueda semántica
# --------------------------------------------------------------------------- #
def _cosine(a: list[float], b: list[float]) -> float:
    import math

    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


def search(query: str, top_k: int | None = None, session: str | None = None, tags: list[str] | None = None) -> list[dict]:
    """Busca los segmentos más similares semánticamente a la consulta.

    Si ``session`` se indica, filtra solo los segmentos de esa sesión (por nombre).
    Si ``tags`` se indica, filtra solo sesiones que tengan alguno de esos tags.
    """
    index = load_index()
    segments = index.get("segments") or []
    if not segments:
        raise SystemExit(
            "No hay índice de embeddings. Corre: python -m notekeeper embed-index"
        )

    if session:
        segments = [s for s in segments if s.get("session") == session]
    if tags:
        from notekeeper.storage import get_tags
        tag_set = {t.lower() for t in tags}
        valid = set()
        seen = set()
        for s in segments:
            sid = s.get("session")
            if sid not in seen:
                seen.add(sid)
                if tag_set.intersection(get_tags(DATA_DIR / sid)):
                    valid.add(sid)
        segments = [s for s in segments if s.get("session") in valid]
        if not segments:
            return []

    qvec = embed([query])[0]
    top_k = top_k or EMBEDDING_TOP_K

    scored = []
    for seg in segments:
        score = _cosine(qvec, seg.get("vector") or [])
        scored.append((score, seg))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Filtros de similitud: piso absoluto y umbral relativo al mejor resultado.
    if scored:
        top_score = scored[0][0]
        kept = []
        for score, seg in scored:
            if EMBEDDING_MIN_SIM > 0 and score < EMBEDDING_MIN_SIM:
                continue
            if (
                EMBEDDING_REL_SIM > 0
                and top_score > 0
                and score < top_score * EMBEDDING_REL_SIM
            ):
                continue
            kept.append((score, seg))
        scored = kept

    return [
        {
            "session": seg["session"],
            "start": seg.get("start"),
            "text": seg["text"],
            "speaker": seg.get("speaker"),
            "speaker_label": seg.get("speaker_label"),
            "score": round(score, 4),
        }
        for score, seg in scored[:top_k]
    ]


def semantic_context(query: str, top_k: int | None = None, session: str | None = None, tags: list[str] | None = None) -> str:
    """Construye un contexto en texto con los fragmentos más relevantes."""
    results = search(query, top_k, session=session, tags=tags)
    if not results:
        return "(sin resultados relevantes)"

    from notekeeper.context import _fmt_time

    lines = []
    for r in results:
        ts = _fmt_time(r["start"]) if r["start"] is not None else "?"
        label = r.get("speaker_label")
        speaker = f"{label}: " if label else ""
        lines.append(f"[{r['session']} {ts} (sim {r['score']})] {speaker}{r['text']}")
    return "\n".join(lines)


def tasks_semantic_context(session: str | None = None, top_k: int | None = None, tags: list[str] | None = None) -> str:
    """Contexto para generar tareas Jira a partir de los segmentos relevantes.

    Hace varias consultas semánticas orientadas a detectar acuerdos, decisiones
    y tareas, y combina los fragmentos más relevantes (deduplicados).
    Incluye un encabezado con la lista de reuniones involucradas y su fecha/hora.
    """
    from notekeeper.tasks import _session_datetime

    queries = [
        "acuerdos decisiones y tareas pendientes asumidas por alguien",
        "acciones comprometidas responsables plazos y fechas",
        "problemas bugs pendientes y temas a resolver",
        "quién se encarga de cada tarea yo me encargo me toca a mí lo asumo",
        "asignación de responsables compromisos con el nombre de la persona encargada",
        "queda a cargo de alguien le dejo esto encárgate hazlo tú",
    ]
    top_k = top_k or max(EMBEDDING_TOP_K // 2, 4)

    seen = set()
    blocks = []
    meeting_ids = set()
    for q in queries:
        for r in search(q, top_k=top_k, session=session, tags=tags):
            key = (r["session"], r["start"])
            if key in seen:
                continue
            seen.add(key)
            meeting_ids.add(r["session"])
            from notekeeper.context import _fmt_time

            ts = _fmt_time(r["start"]) if r["start"] is not None else "?"
            label = r.get("speaker_label")
            speaker = f"{label}: " if label else ""
            blocks.append((r["score"], f"[{r['session']} {ts}] {speaker}{r['text']}"))

    blocks.sort(key=lambda x: x[0], reverse=True)

    # Encabezado con las reuniones involucradas y su fecha/hora legible.
    header = []
    if meeting_ids:
        header.append("REUNIONES ANALIZADAS:")
        for mid in sorted(meeting_ids):
            fecha, hora = _session_datetime(mid)
            header.append(f"- {mid} (fecha {fecha}, hora {hora})")
        header.append("")

    body = "\n".join(b for _, b in blocks)
    return "\n".join(header) + (body if body else "(sin resultados relevantes)")
