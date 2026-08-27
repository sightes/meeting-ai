"""Generación de resumen de reunión y tareas Jira desde transcripciones."""
import json
from datetime import date
from pathlib import Path

from notekeeper.config import LLM_API_KEY, LLM_MODEL, LLM_BASE_URL
from notekeeper.storage import save_metadata


def _client():
    if not LLM_API_KEY:
        raise SystemExit(
            "No hay LLM_API_KEY configurada. Agrega tu key en .env (https://openrouter.ai/keys)"
        )
    from openai import OpenAI
    return OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].lstrip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise SystemExit(f"El LLM no devolvió JSON válido:\n{text[:500]}")
        return json.loads(text[start : end + 1])


def generate(context: str, today: str | None = None) -> dict:
    """Pide al LLM un resumen + tareas Jira a partir de un contexto de reuniones."""
    if not context.strip() or context == "(no hay transcripciones)":
        raise SystemExit("No hay transcripciones para generar tareas.")

    today = today or date.today().isoformat()

    client = _client()
    prompt = f"""Eres analista de producto para un equipo que trabaja con Jira.
A partir de las transcripciones de reuniones (indexadas por fecha, la más reciente primero),
genera actividades y decisiones, y convierte los acuerdos/acciones en issues de Jira:
- Divide actividades grandes en múltiples issues accionables.
- Incluye SOLO temas que se acordaron o se plantearon como tarea.
- Escribe todos los campos en español.
- ETA estimada usando {today} como fecha de hoy.
- story_points: 1, 2, 3, 5 u 8 (tamaño de tarea).
- priority: High, Medium o Low.
- assignee: el nombre de la persona responsable si se menciona, si no "".
- session: el nombre exacto del encabezado "### Reunión: <nombre>" de la transcripción de la que salió cada tarea.

Responde ÚNICAMENTE con JSON válido, con esta forma exacta:
{{
  "summary": ["viñeta 1", "viñeta 2", ...],
  "meetings": [
    {{
      "id": "nombre exacto de la reunión (encabezado del bloque)",
      "tema": "tema central de la reunión en máximo 8 palabras"
    }}
  ],
  "tasks": [
    {{
      "title": "título accionable (imperativo, corto)",
      "description": "descripción con contexto y criterio de aceptación (2-5 frases)",
      "issue_type": "Task o Story o Bug",
      "priority": "High o Medium o Low",
      "story_points": 2,
      "eta": "AAAA-MM-DD",
      "assignee": "nombre o ''",
      "session": "nombre exacto de la reunión donde se planteó"
    }}
  ]
}}

TRANSCRIPCIONES (indexadas por fecha, más reciente primero):
{context}
"""
    print("Consultando LLM...")
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": "Siempre respondes solo JSON válido, sin texto adicional."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=2048,
        extra_headers={
            "HTTP-Referer": "https://github.com/sightes/meeting-ai",
            "X-Title": "notekeeper",
        },
    )
    return _extract_json(response.choices[0].message.content)


def render_summary(data: dict) -> str:
    bullets = data.get("summary") or []
    lines = ["=== RESUMEN DE LA REUNIÓN ===", ""]
    for b in bullets:
        lines.append(f"• {b}")
    return "\n".join(lines)


def _session_datetime(session_id: str) -> tuple[str, str]:
    """Deriva fecha y hora legibles desde un id de sesión `YYYY-MM-DD_HH-MM-SS`."""
    fecha, sep, hora = session_id.partition("_")
    if not sep:
        return session_id, "—"
    hh, _, _ = hora.partition("-")
    if "-" in hora:
        hhmm = "-".join(str(int(p)) if p.isdigit() else p for p in hora.split("-")[:2])
        hora = hhmm.replace("-", ":")
    return fecha, hora


def render_meetings(data: dict) -> str:
    """Tabla con el mapeo de reuniones: fecha, hora y tema central."""
    meetings = data.get("meetings") or []
    if not meetings:
        return ""

    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:
        lines = ["=== MAPEO DE REUNIONES ===", ""]
        for m in meetings:
            fecha, hora = _session_datetime(m.get("id") or "")
            lines.append(f"{fecha} {hora}  {m.get('tema', '—')}")
        return "\n".join(lines)

    table = Table(title="MAPEO DE REUNIONES", show_lines=True)
    table.add_column("Fecha", style="cyan")
    table.add_column("Hora", justify="center")
    table.add_column("Tema central", style="bold")

    for m in meetings:
        fecha, hora = _session_datetime(m.get("id") or "")
        table.add_row(fecha, hora, m.get("tema") or "—")

    console = Console(file=__import__("io").StringIO(), force_terminal=False, no_color=True, width=60)
    console.print(table)
    return console.file.getvalue().rstrip()


def render_tasks(data: dict) -> str:
    """Imprime las tareas Jira como una tabla estructurada."""
    tasks = data.get("tasks") or []
    if not tasks:
        return "=== TAREAS JIRA ===\n\n(no se generaron tareas)"

    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:
        return render_tasks_plain(data)

    table = Table(title="TAREAS JIRA", show_lines=True)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Título")
    table.add_column("Tipo", style="cyan")
    table.add_column("Prioridad", style="magenta")
    table.add_column("Pts", justify="center")
    table.add_column("ETA")
    table.add_column("Responsable")
    table.add_column("Reunión\n(fecha/hora)", style="dim")

    for i, t in enumerate(tasks, 1):
        fecha, hora = _session_datetime(t.get("session") or "")
        table.add_row(
            str(i),
            (t.get("title") or "Sin título"),
            t.get("issue_type", "Task"),
            t.get("priority", "-"),
            str(t.get("story_points", "?")),
            t.get("eta") or "—",
            t.get("assignee") or "—",
            f"{fecha} {hora}".rstrip(),
        )

    console = Console(
        file=__import__("io").StringIO(),
        force_terminal=False,
        no_color=True,
        width=170,
    )
    console.print(table)
    buf = console.file.getvalue().rstrip()

    desc_lines = []
    for i, t in enumerate(tasks, 1):
        desc = (t.get("description") or "").strip()
        if desc:
            desc_lines.append(f"  {i}. {desc}")

    if desc_lines:
        buf += "\n\nDETALLES:\n" + "\n".join(desc_lines)
    return buf


def render_tasks_plain(data: dict) -> str:
    """Fallback sin rich: texto plano."""
    tasks = data.get("tasks") or []
    lines = ["=== TAREAS JIRA ===", ""]
    for i, t in enumerate(tasks, 1):
        eta = t.get("eta") or "—"
        assignee = t.get("assignee") or "—"
        fecha, hora = _session_datetime(t.get("session") or "")
        lines.append(
            f"{i}. {t.get('title', 'Sin título')}  "
            f"[{t.get('issue_type', 'Task')}/{t.get('priority', '-')}/"
            f"{t.get('story_points', '?')}pts/ETA {eta}/{assignee}/"
            f"Reunión {fecha} {hora}]"
        )
        desc = (t.get("description") or "").strip()
        if desc:
            lines.append(f"   {desc}")
        lines.append("")
    return "\n".join(lines)


def to_csv(data: dict) -> str:
    import csv
    import io

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Summary", "Issue Type", "Description", "Priority", "Story Points", "Due Date", "Assignee", "Session", "Meeting Date", "Meeting Time"])
    for t in data.get("tasks") or []:
        fecha, hora = _session_datetime(t.get("session") or "")
        writer.writerow([
            t.get("title", ""),
            t.get("issue_type", "Task"),
            t.get("description", ""),
            t.get("priority", "Medium"),
            t.get("story_points", ""),
            t.get("eta", ""),
            t.get("assignee", ""),
            t.get("session", ""),
            fecha,
            hora,
        ])
    return buf.getvalue()


def run(context: str, session: Path) -> dict:
    """Genera, guarda y devuelve el resultado (summary + tasks) para la sesión."""
    data = generate(context)

    (session / "tasks.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (session / "jira_tasks.csv").write_text(to_csv(data), encoding="utf-8-sig")
    mapeo = render_meetings(data)
    report = render_summary(data) + "\n\n"
    if mapeo:
        report += mapeo + "\n\n"
    report += render_tasks(data)
    (session / "meeting_summary.txt").write_text(report, encoding="utf-8")
    save_metadata(session, {"jira_tasks": len(data.get("tasks") or [])})

    return data