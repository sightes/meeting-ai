"""Exportación opcional de reuniones a Notas y Recordatorios de macOS.

Crea una nota en Apple Notes con el resumen de la reunión (`meeting_summary.txt`)
y un recordatorio por cada tarea de `tasks.json`. Usa AppleScript vía `osascript`.

Modo ``--dry-run``: solo muestra la nota y los recordatorios que se crearían,
sin tocar iCloud ni pedir permisos de automatización.
"""
import json
import re
import subprocess
from pathlib import Path

PRIORITY_MAP = {"high": "1", "medium": "5", "low": "9"}  # Recordatorios: 1 alta, 5 media, 9 baja


def plan_session(session: Path) -> dict:
    """Devuelve el plan de exportación (nota + recordatorios) para una sesión.

    No toca nada del sistema; solo lee los archivos y estructura el resultado.
    """
    summary_file = session / "meeting_summary.txt"
    tasks_file = session / "tasks.json"

    summary = summary_file.read_text(encoding="utf-8") if summary_file.exists() else ""
    tasks = []
    if tasks_file.exists():
        raw = json.loads(tasks_file.read_text(encoding="utf-8"))
        tasks = raw.get("tasks") or []

    from notekeeper.storage import load_metadata

    meta = load_metadata(session)

    note = {
        "title": _note_title(session, meta),
        "folder": meta.get("notes_folder") or "Reuniones",
        "body": summary,
    }

    reminders = []
    for t in tasks:
        reminders.append(_reminder_from_task(t))

    return {"session": session.name, "note": note, "reminders": reminders}


def _note_title(session: Path, meta: dict) -> str:
    tags = sorted(str(t).strip() for t in (meta.get("tags") or []) if str(t).strip())
    tag_str = ("[" + ", ".join(tags) + "] ") if tags else ""
    tema = meta.get("topic") or meta.get("tema") or ""
    if not tema:
        # Extraer el tema del tasks.json (campo meetings[].tema) si existe.
        tasks_file = session / "tasks.json"
        if tasks_file.exists():
            try:
                raw = json.loads(tasks_file.read_text(encoding="utf-8"))
                meetings = raw.get("meetings") or []
                for m in meetings:
                    if m.get("id") == session.name and m.get("tema"):
                        tema = m["tema"]
                        break
                if not tema and meetings:
                    tema = meetings[0].get("tema") or ""
            except (json.JSONDecodeError, OSError):
                pass
    date_part = session.name.split("_")[0]
    title = f"{tag_str}{date_part}"
    if tema:
        title += f" — {tema}"
    return title


def _reminder_from_task(t: dict) -> dict:
    return {
        "title": t.get("title") or "Sin título",
        "notes": t.get("description") or "",
        "priority": PRIORITY_MAP.get((t.get("priority") or "").strip().lower(), "5"),
        "due": _due_date(t.get("eta") or ""),
        "list": "Reuniones",
    }


def _due_date(eta: str) -> str | None:
    """Convierte YYYY-MM-DD a fecha legible para Recordatorios."""
    if not eta or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", eta):
        return None
    return f"{eta} a las 09:00:00"


def _title_is(title: str) -> str:
    return json.dumps(str(title), ensure_ascii=True)


def _esc(text: str) -> str:
    """Escapa un texto para insertarlo como literal AppleScript (entre comillas)."""
    text = str(text or "")
    text = text.replace('\\', '\\\\').replace('"', '\\"')
    return '"' + text + '"'


def _gh_run(args: list[str]) -> str:
    """Ejecuta un comando (osascript) y devuelve stdout, o lanza SystemExit."""
    try:
        proc = subprocess.run(args, capture_output=True, text=True, check=False, timeout=60)
    except FileNotFoundError:
        raise SystemExit("No se encontró osascript (¿no es macOS?).")
    except subprocess.TimeoutExpired:
        raise SystemExit("osascript tardó demasiado (timeout). ¿Está abierta la app?"
                         " Reintenta o abre Notas/Recordatorios.")
    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip() or "error desconocido"
        raise SystemExit(msg)
    return proc.stdout


def create_note_script(note: dict) -> str:
    folder = _esc(note.get("folder") or "Reuniones")
    body = _esc(note.get("body") or "")
    return (
        "tell application \"Notes\"\n"
        "  set targetFolder to first folder whose name is " + folder + "\n"
        "  set newNote to make new note at targetFolder with properties {body: " + body + "}\n"
        "  return id of newNote\n"
        "end tell\n"
    )


def create_reminder_script(reminder: dict) -> str:
    name = _esc(reminder.get("title") or "")
    notes = _esc(reminder.get("notes") or "")
    priority = reminder.get("priority") or "5"
    lines = ['tell application "Reminders"']
    lines.append(f'  set newReminder to make new reminder with properties {{name: {name}, body: {notes}, priority: {priority}}}')
    due = reminder.get("due")
    if due:
        lines.append(f'  set due date of newReminder to date "{due}"')
    lines.append("  return (id of newReminder) as string")
    lines.append("end tell")
    return "\n".join(lines) + "\n"


def render_plan(session: Path, plan: dict) -> str:
    """Texto legible del plan (usado por --dry-run)."""
    lines = [f"=== {session.name} ===", ""]
    note = plan["note"]
    lines.append("NOTA (Notas de Apple)")
    lines.append(f"  Carpeta: {note['folder']}")
    lines.append(f"  Título : {note['title']}")
    lines.append(f"  Cuerpo : {len(note['body'])} caracteres")
    lines.append("")

    rems = plan["reminders"]
    lines.append(f"RECORDATORIOS ({len(rems)})")
    if not rems:
        lines.append("  (sin tareas para esta sesión)")
    for r in rems:
        due = r.get("due") or "sin fecha"
        lines.append(f"  • {r['title']}  [prioridad {r['priority']}] [vence {due}]")
    lines.append("")
    return "\n".join(lines)
