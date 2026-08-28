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
    """Extrae un objeto JSON válido de la respuesta del LLM, de forma robusta."""
    text = text.strip()

    def _try(s: str):
        s = s.strip()
        if s.startswith("```"):
            s = s.strip("`")
            if s.startswith("json"):
                s = s[4:].lstrip()
        return json.loads(s)

    # 1) Intento directo (y con fences)
    try:
        return _try(text)
    except json.JSONDecodeError:
        pass

    # 2) Buscar el primer objeto {...} balanceado completo, respetando strings
    start = text.find("{")
    while start != -1:
        try:
            end = _matching_brace(text, start)
            return _try(text[start : end + 1])
        except (json.JSONDecodeError, ValueError):
            start = text.find("{", start + 1)

    raise SystemExit(
        "El LLM no devolvió JSON válido (¿respuesta truncada por límite de tokens? "
        "Aumenta 'max_tokens' o baja la cantidad de reuniones con -n).\n"
        f"Respuesta (inicio): {text[:400]}"
    )


def _matching_brace(text: str, start: int) -> int:
    """Devuelve el índice de la llave `}` que cierra la `{` en `start`."""
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    raise ValueError("no se encontró llave de cierre balanceada")


def _ask_json(client, prompt: str, max_tokens: int) -> dict:
    """Una llamada al LLM que debe devolver un JSON (extracción robusta)."""
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": "Siempre respondes solo JSON válido, sin texto adicional."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=max_tokens,
        extra_headers={
            "HTTP-Referer": "https://github.com/sightes/meeting-ai",
            "X-Title": "notekeeper",
        },
    )
    return _extract_json(response.choices[0].message.content)


def generate(context: str, today: str | None = None) -> dict:
    """Pide al LLM un resumen + tareas Jira en dos fases.

    1) Resumen y mapeo de reuniones (JSON corto, sin truncar).
    2) Tareas Jira a partir del resumen + las transcripciones completas.
    Evita que una sola respuesta gigante mezcle ambas cosas y quede truncada.
    """
    if not context.strip() or context == "(no hay transcripciones)":
        raise SystemExit("No hay transcripciones para generar tareas.")

    today = today or date.today().isoformat()
    client = _client()

    base = (
        "Eres analista de producto para un equipo que trabaja con Jira.\n"
        "A partir de las transcripciones de reuniones (indexadas por fecha, la más reciente primero):\n"
        "- Escribe todos los campos en español.\n"
        "- ETA estimada usando {today} como fecha de hoy.\n"
        "- story_points: 1, 2, 3, 5 u 8 (tamaño de tarea).\n"
        "- priority: High, Medium o Low.\n"
        "- assignee: el nombre de la persona responsable si se menciona o se infiere del hablante del fragmento (fragmentos diarizados vienen con prefijo \"Nombre: \" o \"Locutor N: \"); si claramente no hay responsable, \"\".\n"
        "- session: el nombre exacto del encabezado \"### Reunión: <nombre>\" de la transcripción de la que salió cada tarea.\n"
    ).format(today=today)

    # ---- Fase 1: resumen + mapeo de reuniones (poca salida, sin truncamiento) ----
    summary_prompt = base + f"""
Responde ÚNICAMENTE con JSON válido, con esta forma exacta:
{{
  "summary": ["viñeta 1", "viñeta 2", ...],
  "decisiones": [
    {{
      "que": "decisión tomada (imperativo o hecho)",
      "sesion": "nombre exacto de la reunión donde se decidió",
      "responsable": "responsable si aplica, si no ''"
    }}
  ],
  "acuerdos": ["acuerdo 1", "acuerdo 2", ...],
  "pendientes": [
    {{
      "que": "acción pendiente",
      "responsable": "responsable si aplica, si no ''",
      "para_cuando": "fecha o 'sin fecha'"
    }}
  ],
  "bloqueantes": ["bloqueante 1", ...],
  "meetings": [
    {{
      "id": "nombre exacto de la reunión (encabezado del bloque)",
      "tema": "tema central de la reunión en máximo 8 palabras"
    }}
  ]
}}

Las listas "decisiones", "acuerdos", "pendientes" y "bloqueantes" son OPCIONALES:
inclúyelas solo si hay contenido real en las transcripciones; si no, usa [].
Prioriza claridad y concreción (quién, qué, cuándo) en cada ítem.

TRANSCRIPCIONES (indexadas por fecha, más reciente primero):
{context}
"""
    print("Consultando LLM (resumen)...")
    data = _ask_json(client, summary_prompt, max_tokens=1200)

    # ---- Fase 2: tareas Jira desde el resumen + transcripciones ----
    bullets = data.get("summary") or []
    resumen_bloque = "### RESUMEN DE REUNIONES\n" + "\n".join(f"- {b}" for b in bullets)

    tasks_prompt = base + f"""
Convierte los acuerdos/acciones en issues de Jira:
- Divide actividades grandes en múltiples issues accionables.
- Incluye SOLO temas que se acordaron o se plantearon como tarea.
- session: nombre exacto de la reunión (encabezado "### Reunión: <nombre>") de donde salió cada tarea; usa también el resumen para ubicarla.

Responde ÚNICAMENTE con JSON válido, con esta forma exacta:
{{
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

{resumen_bloque}

TRANSCRIPCIONES (indexadas por fecha, más reciente primero):
{context}
"""
    print("Consultando LLM (tareas)...")
    tasks = _ask_json(client, tasks_prompt, max_tokens=3200).get("tasks") or []
    data["tasks"] = tasks
    return data


def _sec(title: str) -> str:
    return f"\n── {title} ──"


def render_summary(data: dict) -> str:
    lines = ["=== RESUMEN DE LA REUNIÓN ===", ""]

    bullets = data.get("summary") or []
    if bullets:
        for b in bullets:
            lines.append(f"• {b}")

    decisiones = data.get("decisiones") or []
    if decisiones:
        lines.append(_sec("DECISIONES"))
        for d in decisiones:
            quien = (d.get("responsable") or "").strip()
            extra = f"  → Responsable: {quien}" if quien else ""
            lines.append(f"• {d.get('que', '')}{extra}")

    acuerdos = data.get("acuerdos") or []
    if acuerdos:
        lines.append(_sec("ACUERDOS"))
        for a in acuerdos:
            lines.append(f"• {a}")

    pendientes = data.get("pendientes") or []
    if pendientes:
        lines.append(_sec("PENDIENTES / PRÓXIMOS PASOS"))
        for p in pendientes:
            who = (p.get("responsable") or "").strip()
            cuando = (p.get("para_cuando") or "").strip()
            partes = []
            if who:
                partes.append(f"Responsable: {who}")
            if cuando:
                partes.append(f"Para: {cuando}")
            ext = f"  ({', '.join(partes)})" if partes else ""
            lines.append(f"• {p.get('que', '')}{ext}")

    bloqueantes = data.get("bloqueantes") or []
    if bloqueantes:
        lines.append(_sec("BLOQUEANTES"))
        for b in bloqueantes:
            lines.append(f"• ⚠ {b}")

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
            fecha, hora = m.get("fecha"), m.get("hora")
            if not fecha:
                fecha, hora = _session_datetime(m.get("id") or "")
            lines.append(f"{fecha} {hora}  {m.get('tema', '—')}")
        return "\n".join(lines)

    table = Table(title="MAPEO DE REUNIONES", show_lines=True)
    table.add_column("Fecha", style="cyan")
    table.add_column("Hora", justify="center")
    table.add_column("Tema central", style="bold")

    for m in meetings:
        fecha, hora = m.get("fecha"), m.get("hora")
        if not fecha:
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


def _enrich_meetings(data: dict) -> dict:
    """Completa `meetings` con fecha/hora derivadas de las sesiones reales.

    El LLM puede no rellenar el campo `meetings` (sobre todo en modo embeddings),
    así que derivamos fecha y hora de las sesiones transcritas y usamos el tema
    del LLM como complemento cuando coincida el id.
    """
    from notekeeper.storage import list_sessions, get_transcript_text

    llm_meetings = {
        (m.get("id") or ""): m for m in (data.get("meetings") or []) if m.get("id")
    }
    meetings = []
    for s in list_sessions():
        if not get_transcript_text(s):
            continue
        fecha, hora = _session_datetime(s.name)
        tema = llm_meetings.get(s.name, {}).get("tema", "")
        meetings.append({"id": s.name, "fecha": fecha, "hora": hora, "tema": tema or ""})
    data["meetings"] = meetings
    return data


def run(context: str, session: Path) -> dict:
    """Genera, guarda y devuelve el resultado (summary + tasks) para la sesión."""
    data = generate(context)
    _enrich_meetings(data)

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