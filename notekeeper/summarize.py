"""Generación de archivos MD de resumen para cada reunión resumida.

Cada sesión en ``recordings/`` que tenga un ``meeting_summary.txt`` se
convierte a un archivo ``summaries/[tag][fecha][tema].md``. Si el archivo ya
existe, se reemplaza.
"""
import re
from pathlib import Path

from notekeeper.storage import list_sessions, load_metadata

SUMMARIES_DIR = Path("summaries")


def _tags(metadata: dict) -> list[str]:
    return sorted(str(t).strip().lower() for t in (metadata.get("tags") or []) if str(t).strip())


def _extract_topic(meeting_summary: str, session_name: str) -> str:
    """Extrae el tema central de la tabla MAPEO DE REUNIONES.

    Busca la fila cuya fecha coincida con la de la sesión; si no la encuentra,
    usa la primera fila con tema. Devuelve un slug limpio.
    """
    # Fecha de la sesión: YYYY-MM-DD del nombre del directorio
    date_part = re.match(r"(\d{4}-\d{2}-\d{2})", session_name)
    session_date = date_part.group(1) if date_part else None

    rows = []
    for line in meeting_summary.splitlines():
        if "│" not in line:
            continue
        cells = [c.strip() for c in line.split("│")]
        # Una fila real de la tabla de reuniones tiene al menos [fecha, hora, tema...]
        cells = [c for c in cells if c]
        if len(cells) >= 3 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", cells[0]):
            rows.append((cells[0], cells[1], " ".join(cells[2:])))

    topic = ""
    if session_date:
        for fecha, _hora, tema in rows:
            if fecha == session_date and tema:
                topic = tema
                break
    if not topic and rows:
        topic = rows[0][2]

    return _slug(topic)


def _slug(text: str, max_len: int = 40) -> str:
    """Convierte un texto a un slug seguro para nombres de archivo."""
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    if len(text) > max_len:
        text = text[:max_len].rstrip("-")
    return text


def _filename(session: Path, metadata: dict, meeting_summary: str) -> str:
    tags = "-".join(_tags(metadata))
    fecha = session.name.split("_")[0]
    tema = _extract_topic(meeting_summary, session.name)
    parts = [p for p in (tags, fecha, tema) if p]
    return "_".join(parts) + ".md" if parts else session.name + ".md"


def summarize_session(session: Path) -> tuple[Path, bool]:
    """Genera el archivo MD de resumen para una sesión.

    Devuelve ``(ruta, replaced)`` donde ``replaced`` es True si el archivo de
    destino ya existía y fue sobreescrito.
    """
    summary_file = session / "meeting_summary.txt"
    if not summary_file.exists():
        raise FileNotFoundError(f"{session.name}: no tiene meeting_summary.txt")

    meeting_summary = summary_file.read_text(encoding="utf-8")
    metadata = load_metadata(session)
    name = _filename(session, metadata, meeting_summary)

    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SUMMARIES_DIR / name
    replaced = out_path.exists()
    out_path.write_text(meeting_summary, encoding="utf-8")
    return out_path, replaced


def resume_all() -> None:
    """Procesa todas las sesiones con resumen y reporta creadas/reemplazadas."""
    sessions = [s for s in list_sessions() if (s / "meeting_summary.txt").exists()]
    if not sessions:
        print("No hay reuniones resumidas (busca meeting_summary.txt en sessions).")
        return

    created = 0
    replaced = 0
    for s in sessions:
        out, was_replaced = summarize_session(s)
        if was_replaced:
            replaced += 1
            state = "reemplazado"
        else:
            created += 1
            state = "creado"
        print(f"  {s.name} -> {out.name} ({state})")

    print(f"\n{len(sessions)} reunión(es) procesada(s): {created} creada(s), "
          f"{replaced} reemplazada(s).")
