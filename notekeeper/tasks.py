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
- season: el nombre/nombre_id de la reunión de la que salió cada tarea.

Responde ÚNICAMENTE con JSON válido, con esta forma exacta:
{{
  "summary": ["viñeta 1", "viñeta 2", ...],
  "tasks": [
    {{
      "title": "título accionable (imperativo, corto)",
      "description": "descripción con contexto y criterio de aceptación (2-5 frases)",
      "issue_type": "Task o Story o Bug",
      "priority": "High o Medium o Low",
      "story_points": 2,
      "eta": "AAAA-MM-DD",
      "assignee": "nombre o ''",
      "session": "id de la reunión donde se planteó"
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
            "HTTP-Referer": "https://github.com/openai/notekeeper",
            "X-Title": "notekeeper-jira-tasks",
        },
    )
    return _extract_json(response.choices[0].message.content)


def render_summary(data: dict) -> str:
    bullets = data.get("summary") or []
    lines = ["=== RESUMEN DE LA REUNIÓN ===", ""]
    for b in bullets:
        lines.append(f"• {b}")
    return "\n".join(lines)


def render_tasks(data: dict) -> str:
    tasks = data.get("tasks") or []
    lines = ["=== TAREAS JIRA ===", ""]
    for i, t in enumerate(tasks, 1):
        eta = t.get("eta") or "—"
        assignee = t.get("assignee") or "—"
        lines.append(
            f"{i}. {t.get('title', 'Sin título')}  "
            f"[{t.get('issue_type', 'Task')}/{t.get('priority', '-')}/"
            f"{t.get('story_points', '?')}pts/ETA {eta}/{assignee}]"
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
    writer.writerow(["Summary", "Issue Type", "Description", "Priority", "Story Points", "Due Date", "Assignee", "Session"])
    for t in data.get("tasks") or []:
        writer.writerow([
            t.get("title", ""),
            t.get("issue_type", "Task"),
            t.get("description", ""),
            t.get("priority", "Medium"),
            t.get("story_points", ""),
            t.get("eta", ""),
            t.get("assignee", ""),
            t.get("session", ""),
        ])
    return buf.getvalue()


def run(context: str, session: Path) -> dict:
    """Genera, guarda y devuelve el resultado (summary + tasks) para la sesión."""
    data = generate(context)

    (session / "tasks.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (session / "jira_tasks.csv").write_text(to_csv(data), encoding="utf-8-sig")
    (session / "meeting_summary.txt").write_text(
        render_summary(data) + "\n\n" + render_tasks(data), encoding="utf-8"
    )
    save_metadata(session, {"jira_tasks": len(data.get("tasks") or [])})

    return data