"""Diarización de hablantes sobre las grabaciones (opcional).

Anota cada segmento de ``segments.json`` con la etiqueta del hablante
(``SPEAKER_00``, ``SPEAKER_01``...) usando ``pyannote.audio``. Esas
etiquetas se incluyen luego en el índice de embeddings y en el contexto
que recibe el LLM, para que los responsables (hablantes) aparezcan en la
generación de tareas Jira.
"""
import json
from pathlib import Path

from notekeeper.config import HF_TOKEN, DIARIZATION_MODEL, DIARIZATION_DEVICE
from notekeeper.storage import get_audio_path, save_metadata, load_metadata


_pipeline = None


def _to_device(pipeline):
    """Mueve el pipeline a GPU/MPS si está disponible (o usa el override de .env)."""
    try:
        import torch
    except ImportError:
        return pipeline

    device = DIARIZATION_DEVICE
    if device == "auto":
        if torch.cuda.is_available():
            device = "cuda"
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"

    if device == "cpu":
        return pipeline
    try:
        pipeline.to(torch.device(device))
        print(f"Diarización en {device}")
    except Exception as exc:
        print(f"No se pudo usar {device} ({exc}); usando CPU.")
    return pipeline


def _require_pipeline():
    """Carga (una sola vez) el pipeline de diarización de pyannote."""
    global _pipeline
    if _pipeline is not None:
        return _pipeline
    if not HF_TOKEN:
        raise SystemExit(
            "Para diarizar necesitas HF_TOKEN en .env (token de HuggingFace) con "
            "acceso al modelo.\n"
            f"1. Crea un token en https://huggingface.co/settings/tokens\n"
            f"2. Acepta la licencia de {DIARIZATION_MODEL} (botón 'Agree and access')\n"
            f"   https://huggingface.co/{DIARIZATION_MODEL}\n"
            f"3. Agrega HF_TOKEN=hf_xxxx en .env"
        )
    try:
        from pyannote.audio import Pipeline
    except ImportError as exc:
        raise SystemExit(
            "Para diarizar instala pyannote.audio: pip install pyannote.audio\n"
            "(requiere PyTorch/torchaudio y un token de HuggingFace)."
        ) from exc
    _pipeline = Pipeline.from_pretrained(DIARIZATION_MODEL, token=HF_TOKEN)
    _to_device(_pipeline)
    return _pipeline


def _turns(audio_path: Path) -> list[dict]:
    """Devuelve los turnos de habla: [{"start", "end", "speaker"}, ...]."""
    pipeline = _require_pipeline()
    result = pipeline(str(audio_path))
    # pyannote >= 4.0 devuelve un DiarizeOutput (.speaker_diarization);
    # versiones <= 3.x devolvían el Annotation directamente.
    annotation = getattr(result, "speaker_diarization", result)
    turns = []
    for turn in annotation.itertracks(yield_label=True):
        segment, _, label = turn
        turns.append({"start": segment.start, "end": segment.end, "speaker": label})
    return turns


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _speaker_for(seg: dict, turns: list[dict]) -> str | None:
    """Etiqueta del hablante con mayor solape con el segmento (o None)."""
    best = None
    best_overlap = 0.0
    for t in turns:
        ov = _overlap(seg["start"], seg["end"], t["start"], t["end"])
        if ov > best_overlap:
            best_overlap = ov
            best = t["speaker"]
    if best is None or best_overlap <= 0:
        return None
    return best


def diarize_session(session: Path, verbose: bool = True) -> list[tuple[str, int]]:
    """Anota ``segments.json`` de una sesión con su hablante por segmento.

    Devuelve el conteo de turnos por hablante ``[(speaker, segundos), ...]``
    para mostrar un resumen.
    """
    seg_path = session / "segments.json"
    if not seg_path.exists():
        raise SystemExit(f"{session.name}: no hay segments.json (transcribe primero).")

    audio = get_audio_path(session)
    if not audio:
        raise SystemExit(f"{session.name}: no hay audio para diarizar.")

    if verbose:
        print(f"Diarizando {session.name}...")
    turns = _turns(audio)

    segments = json.loads(seg_path.read_text(encoding="utf-8"))
    speakers = {t["speaker"] for t in turns}
    for seg in segments:
        seg["speaker"] = _speaker_for(seg, turns) if speakers else None
    seg_path.write_text(
        json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    counts: dict[str, int] = {}
    for seg in segments:
        spk = seg.get("speaker")
        if spk:
            counts[spk] = counts.get(spk, 0) + 1

    save_metadata(session, {"diarized": True, "speaker_count": len(counts)})
    if verbose:
        print(f"Hablantes detectados: {len(counts)}")
    return sorted(counts.items())


def speakers_map(session: Path) -> dict[str, str]:
    """Mapeo ``{etiqueta: nombre}`` configurado en metadata.json ("speakers")."""
    meta = load_metadata(session)
    return {k: v for k, v in (meta.get("speakers") or {}).items() if v}


def map_speaker_names(session: Path, counts: list[tuple[str, int]]) -> dict[str, str]:
    """Pide interactivamente el nombre real de cada hablante y lo guarda."""
    names = speakers_map(session)
    print("\nEtiqueta los hablantes (Enter para dejar sin nombre):")
    for spk, n in counts:
        actual = input(f"  {spk} ({n} segmentos) -> ¿nombre? [{names.get(spk, '')}] ").strip()
        if actual:
            names[spk] = actual
    save_metadata(session, {"speakers": names})
    return names


def speaker_label(session: Path, raw: str | None) -> str | None:
    """Nombre amigable del hablante.

    Si el usuario asignó nombres reales (metadata.json "speakers") usa ese;
    si no, usa un etiqueta automática estable "Locutor N" (ordenado por
    aparición dentro de la sesión).
    """
    if not raw:
        return None
    names = speakers_map(session)
    if raw in names:
        return names[raw]
    seg_path = session / "segments.json"
    speakers = set()
    if seg_path.exists():
        try:
            segments = json.loads(seg_path.read_text(encoding="utf-8"))
            speakers = {seg.get("speaker") for seg in segments if seg.get("speaker")}
        except (json.JSONDecodeError, OSError):
            pass
    ordered = sorted(speakers)
    if raw in ordered:
        return f"Locutor {ordered.index(raw) + 1}"
    return raw