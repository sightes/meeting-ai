"""Envío de tareas Jira a un panel GitHub Projects v2.

Crea issues nuevos en un repositorio y los agrega a un panel de proyecto.
Usa la CLI de GitHub (``gh``) como transporte (REST para crear issues,
GraphQL para el panel de proyecto). Reutiliza el LLM para detectar
tareas que ya existen y evitar duplicados.
"""
import json
import re
import subprocess
from datetime import date
from pathlib import Path

from notekeeper.config import (
    GITHUB_ASSIGNEE,
    GITHUB_PRIORITY_MAP,
    GITHUB_PROJECT_URL,
    GITHUB_REPO,
    GITHUB_SIZE_MAP,
    GITHUB_STATUS_INITIAL,
    LLM_API_KEY,
    LLM_MODEL,
    LLM_BASE_URL,
)
from notekeeper.storage import get_tags


GITHUB_DISABLED = (
    "GITHUB_REPO y/o GITHUB_PROJECT_URL no están configurados en .env. "
    "No se enviaron tareas a GitHub. (configura GITHUB_REPO y GITHUB_PROJECT_URL para activarlo)"
)


def _gh(args: list[str]) -> str:
    """Ejecuta un comando gh y devuelve stdout (o lanza SystemExit con el error)."""
    try:
        proc = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        raise SystemExit("No se encontró la CLI `gh`. Instálala: https://cli.github.com/")
    if proc.returncode != 0:
        raise SystemExit(f"Error de gh ({' '.join(args)}):\n{proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def _gh_graphql(query: str, variables: dict | None = None) -> dict:
    """Ejecuta una query/mutación GraphQL vía gh y devuelve el JSON.

    gh api graphql coloca automáticamente cada flag '-f key=value' dentro de
    'variables' cuando se le pasa también '-f query='.
    """
    args = ["api", "graphql", "-f", f"query={query}"]
    for k, v in (variables or {}).items():
        args += ["-F", f"{k}={v}"]
    out = _gh(args)
    return json.loads(out)


def enabled() -> bool:
    return bool(GITHUB_REPO) and bool(GITHUB_PROJECT_URL)


def _parse_project_url(url: str) -> tuple[str, str]:
    """De 'https://github.com/users/sightes/projects/9/views/1' -> ('sightes', '9').

    Soporta organizaciones (orgs/...) y usuarios (users/...), con o sin /views/N.
    """
    m = re.search(r"github\.com/(?:orgs|users)/([^/]+)/projects/(\d+)", url)
    if not m:
        raise SystemExit(f"No se pudo parsear GITHUB_PROJECT_URL: {url!r}")
    return m.group(1), m.group(2)


def _project_id(owner: str, number: str) -> str:
    q = """
    query($owner: String!, $number: Int!) {
      user(login: $owner) { projectV2(number: $number) { id title } }
    }
    """
    data = _gh_graphql(q, {"owner": owner, "number": int(number)})
    proj = data.get("data", {}).get("user", {}).get("projectV2")
    if not proj:
        # intentar como organización
        q = """
        query($owner: String!, $number: Int!) {
          organization(login: $owner) { projectV2(number: $number) { id title } }
        }
        """
        data = _gh_graphql(q, {"owner": owner, "number": int(number)})
        proj = data.get("data", {}).get("organization", {}).get("projectV2")
    if not proj:
        raise SystemExit(f"No se encontró el proyecto #{number} de '{owner}'.")
    return proj["id"]


def _existing_issue_titles(repo: str) -> list[str]:
    """Devuelve los títulos de los issues existentes en el repo (open + closed)."""
    # Pagina con REST; api issues retorna hasta 100 por página.
    out = _gh(["api", f"repos/{repo}/issues", "--jq", ".[] | .title"])
    return [l for l in out.splitlines() if l.strip()]


def _add_to_project(project_id: str, content_id: str) -> str:
    q = """
    mutation($project: ID!, $content: ID!) {
      addProjectV2ItemById(input: {projectId: $project, contentId: $content}) {
        item { id }
      }
    }
    """
    data = _gh_graphql(q, {"project": project_id, "content": content_id})
    item = data.get("data", {}).get("addProjectV2ItemById", {}).get("item", {})
    return item.get("id")


def _project_fields(project_id: str) -> dict[str, dict]:
    """Devuelve los campos del proyecto: {nombre: {id, type, options, option_details}}.

    ``options`` es un mapeo nombre->id para campos de selección única.
    ``option_details`` (solo single-select) mapea nombre -> {id, name, color, description}.
    """
    q = """
    query($project: ID!) {
      node(id: $project) {
        ... on ProjectV2 {
          fields(first: 100) {
            nodes {
              __typename
              ... on ProjectV2FieldCommon { id name }
              ... on ProjectV2SingleSelectField {
                id
                name
                options { id name color description }
              }
            }
          }
        }
      }
    }
    """
    data = _gh_graphql(q, {"project": project_id})
    fields = {}
    nodes = data.get("data", {}).get("node", {}).get("fields", {}).get("nodes", [])
    for n in nodes:
        name = n.get("name")
        if not name:
            continue
        if n.get("__typename") == "ProjectV2SingleSelectField":
            opts = n.get("options") or []
            options = {o["name"]: o["id"] for o in opts}
            details = {o["name"]: o for o in opts}
            fields[name] = {
                "id": n["id"],
                "type": "select",
                "options": options,
                "option_details": details,
            }
        else:
            fields[name] = {"id": n["id"], "type": "other"}
    return fields


def _set_item_field(project_id: str, item_id: str, field_id: str, value: str) -> None:
    """Establece el valor de un campo del item. ``value`` va inline en la query."""
    q = f"""
    mutation {{
      updateProjectV2ItemFieldValue(input: {{
        projectId: "{project_id}"
        itemId: "{item_id}"
        fieldId: "{field_id}"
        value: {value}
      }}) {{ projectV2Item {{ id }} }}
    }}
    """
    _gh_graphql(q)


def _assign_issue(repo: str, number: int, login: str) -> None:
    """Asigna el issue a un usuario (mejor esfuerzo; no rompe si falla)."""
    if not login:
        return
    try:
        _gh(["api", f"repos/{repo}/issues/{number}/assignees", "-f", f"assignees={login}"])
    except SystemExit as e:
        print(f"  ⚠ No se pudo asignar a {login}: {e}")


def _hashtags(text: str) -> list[str]:
    """Devuelve los hashtags (#tag) presentes en un texto, en orden y sin repetir."""
    seen, out = set(), []
    for m in re.finditer(r"(?<!\S)#([\w-]+)", text or ""):
        tag = m.group(1)
        if tag.lower() not in seen:
            seen.add(tag.lower())
            out.append(tag)
    return out


def _existing_labels(repo: str) -> set[str]:
    out = _gh(["api", f"repos/{repo}/labels", "--paginate", "--jq", ".[].name"])
    return {l.lower() for l in out.splitlines() if l.strip()}


def _ensure_labels(repo: str, labels: list[str]) -> None:
    """Crea las labels que no existen aún en el repo (mejor esfuerzo)."""
    if not labels:
        return
    existing = _existing_labels(repo)
    for name in labels:
        if name.lower() in existing:
            continue
        try:
            _gh(["api", f"repos/{repo}/labels", "-f", f"name={name}", "-f", "color=0366d6"])
        except SystemExit as e:
            print(f"  ⚠ No se pudo crear la label '{name}': {e}")


def _apply_labels(repo: str, number: int, labels: list[str]) -> None:
    """Asigna labels a un issue (aditivo: agrega a las que ya tenga)."""
    if not labels:
        return
    try:
        proc = subprocess.run(
            ["gh", "api", "-X", "POST", f"repos/{repo}/issues/{number}/labels",
             "--input", "-"],
            input=json.dumps({"labels": labels}),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise SystemExit(proc.stderr.strip() or proc.stdout.strip())
    except SystemExit as e:
        print(f"  ⚠ No se pudieron asignar labels {labels}: {e}")


def _current_user_login() -> str:
    """Devuelve el login del usuario autenticado en la CLI `gh`."""
    try:
        return _gh(["api", "user", "--jq", ".login"]).strip()
    except SystemExit:
        return ""


def _parse_map(raw: str) -> dict[str, str]:
    """Convierte 'A:x, B:y' en {'A': 'x', 'B': 'y'}."""
    out = {}
    for part in (raw or "").split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        k, _, v = part.partition(":")
        out[k.strip()] = v.strip()
    return out


def _apply_item_fields(project_id: str, item_id: str, fields: dict, task: dict,
                       status: str | None = None) -> None:
    """Rellena Status/Priority/Size/Estimate/Fechas del item a partir de la tarea.

    Solo toca campos que existan en el panel; los que falten o no apliquen se omiten.
    ``status`` (opcional): estado inicial a fijar. Si es None se usa GITHUB_STATUS_INITIAL;
    si es "" no se toca el campo Status.
    """
    if status is None:
        status = GITHUB_STATUS_INITIAL
    priority = (task.get("priority") or "").strip()
    points = task.get("story_points")
    eta = task.get("eta") or ""

    def set_select(field_name: str, option_name: str) -> None:
        f = fields.get(field_name)
        if not f or f.get("type") != "select" or not option_name:
            return
        opt_id = f["options"].get(option_name)
        if not opt_id:
            return
        _set_item_field(project_id, item_id, f["id"], f'{{ singleSelectOptionId: "{opt_id}" }}')

    # Status -> estado inicial (solo si se pide explícitamente)
    if status and fields.get("Status", {}).get("type") == "select":
        opt_id = fields["Status"]["options"].get(status)
        if opt_id:
            _set_item_field(project_id, item_id, fields["Status"]["id"], f'{{ singleSelectOptionId: "{opt_id}" }}')

    # Priority -> opción del campo Priority según el mapeo
    if priority:
        opt = _parse_map(GITHUB_PRIORITY_MAP).get(priority)
        if opt:
            set_select("Priority", opt)

    # Size <- story_points según el mapeo
    if points is not None:
        opt = _parse_map(GITHUB_SIZE_MAP).get(str(points))
        if opt:
            set_select("Size", opt)

    # Estimate <- story_points (campo numérico)
    if points is not None and fields.get("Estimate"):
        try:
            _set_item_field(project_id, item_id, fields["Estimate"]["id"], f"{{ number: {int(points)} }}")
        except (TypeError, ValueError):
            pass

    # Fechas: Start date y Target date <- eta
    if eta and re.fullmatch(r"\d{4}-\d{2}-\d{2}", eta):
        for fname in ("Start date", "Target date"):
            f = fields.get(fname)
            if f:
                try:
                    _set_item_field(project_id, item_id, f["id"], f'{{ date: "{eta}" }}')
                except SystemExit:
                    pass


def _parse_task_from_body(body: str) -> dict:
    """Extrae los metadatos de una tarea desde el body del issue (formato de notekeeper).

    Devuelve ``{priority, story_points, eta}``; los que no aparezcan quedan vacíos/None.
    """
    body = body or ""
    task: dict = {"priority": "", "story_points": None, "eta": ""}

    m = re.search(r"\*\*Prioridad:\*\*\s*(\w+)", body)
    if m:
        task["priority"] = m.group(1)

    m = re.search(r"\*\*Story points:\*\*\s*(\d+)", body)
    if m:
        task["story_points"] = int(m.group(1))

    m = re.search(r"\*\*ETA:\*\*\s*(\d{4}-\d{2}-\d{2})", body)
    if m:
        task["eta"] = m.group(1)

    return task


def _project_items(project_id: str) -> list[dict]:
    """Devuelve los items del proyecto con su issue (number + body) cuando aplica."""
    q = """
    query($project: ID!) {
      node(id: $project) {
        ... on ProjectV2 {
          items(first: 100) {
            nodes {
              id
              content {
                ... on Issue { number title body }
              }
            }
          }
        }
      }
    }
    """
    data = _gh_graphql(q, {"project": project_id})
    nodes = data.get("data", {}).get("node", {}).get("items", {}).get("nodes", [])
    items = []
    for n in nodes:
        content = n.get("content") or {}
        if not content.get("body"):
            continue
        items.append({
            "id": n["id"],
            "number": content.get("number"),
            "title": content.get("title") or "",
            "body": content["body"],
        })
    return items


def backfill_item_fields(force: bool = True) -> None:
    """Rellena los campos de los items YA existentes en el panel.

    Parsea Prioridad/Story points/ETA del body del issue de cada item y rellena
    Priority/Size/Estimate/Fechas (deja el Status tal como está: no lo sobrescribe).
    """
    if not enabled():
        print(GITHUB_DISABLED)
        return

    owner, number = _parse_project_url(GITHUB_PROJECT_URL)
    print(f"Consultando proyecto de GitHub ({owner}/projects/{number})...")
    project_id = _project_id(owner, number)
    fields = _project_fields(project_id)

    items = _project_items(project_id)
    if not items:
        print("No se encontraron items con issue en el panel.")
        return

    print(f"Actualizando {len(items)} item(s) existente(s) en el panel...")
    updated = 0

    # Recolectar todas las labels (hashtags de cada título) y crearlas una sola vez.
    all_labels = []
    for it in items:
        all_labels += _hashtags(it["title"])
    _ensure_labels(GITHUB_REPO, sorted(set(all_labels)))

    for it in items:
        task = _parse_task_from_body(it["body"])
        label = f"#{it['number']}" if it.get("number") else it["id"]
        try:
            _apply_item_fields(project_id, it["id"], fields, task, status="")
            if it.get("number"):
                _apply_labels(GITHUB_REPO, it["number"], _hashtags(it["title"]))
            updated += 1
            print(f"  ✓ #{label}  Prioridad={task['priority'] or '-'}  "
                  f"Pts={task['story_points'] or '-'}  ETA={task['eta'] or '-'}")
        except SystemExit as e:
            print(f"  ✗ #{label} no se pudo actualizar: {e}")
    print(f"Listo: {updated}/{len(items)} item(s) actualizado(s).")


def _gql_str(value: str) -> str:
    """Escapa un string como literal GraphQL (comillas dobles + escapes)."""
    return json.dumps(str(value), ensure_ascii=True)


def _gen_option_descriptions(fields: dict[str, list[dict]]) -> dict[str, dict[str, str]]:
    """Pide al LLM descripciones cortas (español) para las opciones de campos single-select.

    Devuelve {nombre_campo: {opción: descripción}}, solo con las opciones que respondió.
    """
    if not LLM_API_KEY:
        raise SystemExit("Se requiere LLM_API_KEY para generar las descripciones.")

    from openai import OpenAI

    client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)

    block = "\n".join(
        f"- {fname}: [{', '.join(o['name'] for o in options)}]"
        for fname, options in fields.items()
    )
    prompt = f"""Eres un analista de producto que administra un panel de proyecto en GitHub Projects.
Cada campo de selección tiene opciones (que aparecen como columnas en el tablero).
Para cada opción, escribe UNA descripción corta en español (máximo 12 palabras, una sola frase,
sin mencionar el nombre de la opción) que explique qué significa, basándote únicamente en el
nombre del campo y de la opción.

CAMPOS DEL PANEL:
{block}

Responde SOLO con JSON válido, con esta forma:
{{"<campo>": {{"<opción>": "descripción corta", ...}}, ...}}
"""
    resp = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": "Respondes solo JSON válido, sin texto adicional."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=1600,
        extra_headers={
            "HTTP-Referer": "https://github.com/sightes/meeting-ai",
            "X-Title": "notekeeper",
        },
    )
    parsed = _extract_json(resp.choices[0].message.content)

    out: dict[str, dict[str, str]] = {}
    for fname, options in fields.items():
        wanted = {o["name"] for o in options}
        descs = {}
        for oname, text in (parsed.get(fname) or {}).items():
            if isinstance(text, str) and oname in wanted and text.strip():
                descs[oname] = text.strip()
        if descs:
            out[fname] = descs
    return out


def _update_field_options(field_id: str, options: list[dict]) -> None:
    """Fija las opciones de un campo single-select preservando id/nombre/color."""
    rows = []
    for o in options:
        rows.append(
            "{ id: %s, name: %s, color: %s, description: %s }"
            % (_gql_str(o["id"]), _gql_str(o["name"]), o["color"], _gql_str(o["description"]))
        )
    q = f"""
    mutation {{
      updateProjectV2Field(input: {{
        fieldId: "{field_id}"
        singleSelectOptions: [
          {",\n          ".join(rows)}
        ]
      }}) {{
        projectV2Field {{
          ... on ProjectV2SingleSelectField {{ id name options {{ id name description }} }}
        }}
      }}
    }}
    """
    data = _gh_graphql(q)
    if data.get("errors"):
        raise SystemExit(f"No se pudieron fijar las descripciones (campo {field_id}): "
                         f"{data['errors'][0].get('message', data['errors'])}")


def describe_fields(force: bool = False, dry_run: bool = False) -> None:
    """Genera y fija descripciones para las opciones de los campos single-select del panel.

    Solo se tocan las opciones que aún no tienen descripción (salvo ``force``).
    Usa el LLM para redactar las descripciones a partir de los nombres del campo y la opción.
    """
    if not enabled():
        print(GITHUB_DISABLED)
        return

    owner, number = _parse_project_url(GITHUB_PROJECT_URL)
    print(f"Consultando proyecto de GitHub ({owner}/projects/{number})...")
    project_id = _project_id(owner, number)
    fields = _project_fields(project_id)

    targets: dict[str, list[dict]] = {}
    for name, meta in fields.items():
        if meta.get("type") != "select":
            continue
        details = meta.get("option_details") or {}
        pending = [o for o in details.values() if force or not (o.get("description") or "").strip()]
        if pending:
            targets[name] = pending

    if not targets:
        print("Todas las opciones ya tienen descripción. Usa --force para regenerarlas.")
        return

    total = sum(len(v) for v in targets.values())
    print(f"Generando descripciones para {total} opción(es) de {len(targets)} campo(s)...")
    generated = _gen_option_descriptions(targets)
    if not generated:
        print("No se generaron descripciones (respuesta del LLM vacía).")
        return

    if dry_run:
        for fname, descs in generated.items():
            for oname, text in descs.items():
                print(f"  {fname} / {oname}: {text}")
        print("\n(dry-run: no se aplicó nada a GitHub)")
        return

    for fname, descs in generated.items():
        meta = fields[fname]
        options = []
        for oname, text in descs.items():
            o = meta["option_details"][oname]
            options.append({"id": o["id"], "name": o["name"], "color": o["color"], "description": text})
        if not options:
            continue
        print(f"  Actualizando campo '{fname}' ({len(options)} opción(es))...")
        _update_field_options(meta["id"], options)
    print("Listo.")


def _tag_header(tags: set[str]) -> str:
    """Prefijo con hashtags de la sesión (p. ej. '#scotiabank ')."""
    if not tags:
        return ""
    return " ".join(f"#{t}" for t in sorted(tags)) + " "


def dedupe_with_llm(existing_titles: list[str], new_tasks: list[dict]) -> list[dict]:
    """Usa el LLM para decidir qué tareas nuevas ya existen (por similitud semántica).

    Devuelve solo las tareas que NO existen aún.
    """
    if not new_tasks:
        return []
    if not existing_titles:
        return new_tasks

    if not LLM_API_KEY:
        # Sin LLM: dedupe por coincidencia exacta (case-insensitive).
        seen = {t.strip().lower() for t in existing_titles}
        return [t for t in new_tasks if (t.get("title") or "").strip().lower() not in seen]

    from openai import OpenAI

    client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)

    def existing_block(titles):
        if not titles:
            return "(sin issues existentes)"
        return "\n".join(f"- {t}" for t in titles)

    # Si hay muchos issues existentes, los pasamos por lotes para no exceder contexto.
    batch_size = 120
    keep = list(new_tasks)
    for i in range(0, len(existing_titles), batch_size):
        batch = existing_titles[i : i + batch_size]
        prompt = f"""Eres un asistente que evita duplicar issues de Jira en un tablero.
Tienes la lista de issues YA EXISTENTES en el tablero y una lista de TAREAS NUEVAS propuestas.
Para cada tarea nueva, decide si ya está cubierta por uno de los issues existentes (mismo tema
y significado, aunque redactado distinto). Ignora diferencias triviales de redacción.

Responde SOLO con JSON: {{"result": ["title1", "title2", ...]}} con los títulos de las tareas
nuevas que SÍ deben crearse (las que no existen aún). Vacío si todas ya existen.

ISSUES EXISTENTES:
{existing_block(batch)}

TAREAS NUEVAS:
""" + "\n".join(f"- {t.get('title','')}" for t in keep)

        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "Respondes solo JSON válido, sin texto adicional."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=2000,
            extra_headers={
                "HTTP-Referer": "https://github.com/sightes/meeting-ai",
                "X-Title": "notekeeper",
            },
        )
        parsed = _extract_json(resp.choices[0].message.content)
        titles_to_keep = set(parsed.get("result") or [])
        keep = [t for t in keep if t.get("title", "") in titles_to_keep]

    return keep


def _extract_json(text: str) -> dict:
    """Extrae el primer objeto JSON balanceado de la respuesta del LLM."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].lstrip()
    start = text.find("{")
    while start != -1:
        try:
            depth, in_str, esc, i = 0, False, False, start
            for i in range(start, len(text)):
                ch = text[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return json.loads(text[start : i + 1])
            start = text.find("{", start + 1)
        except (json.JSONDecodeError, ValueError):
            start = text.find("{", start + 1)
    raise SystemExit("El LLM no devolvió JSON válido al deduplicar tareas.")


def _attach_tags(task: dict, session: Path | None) -> dict:
    """Agrega los hashtags de la sesión al título de la tarea (si no los tiene)."""
    if not session:
        return task
    tags = get_tags(session)
    if not tags:
        return task
    title = task.get("title", "")
    for t in tags:
        if not re.search(rf"(?<!\S)#{re.escape(t)}\b", title, re.IGNORECASE) and \
           not re.search(rf"(?<!\S)#{re.escape(t)}\b", title.lower()):
            title = f"{_tag_header({t})}{title}" if not title else f"#{t} {title}"
    task["title"] = title
    return task


def sync_tasks(tasks: list[dict], session: Path | None) -> list[dict]:
    """Crea en GitHub las tareas nuevas y las agrega al panel de proyecto.

    Devuelve las tareas que SÍ se crearon.
    """
    if not enabled():
        print(GITHUB_DISABLED)
        return []

    # Adjuntar hashtags de la sesión antes de deduplicar/crear.
    for t in tasks:
        _attach_tags(t, session)

    owner, number = _parse_project_url(GITHUB_PROJECT_URL)
    print(f"Consultando proyecto de GitHub ({owner}/projects/{number}) y issues existentes...")
    project_id = _project_id(owner, number)
    project_fields = _project_fields(project_id)
    existing = _existing_issue_titles(GITHUB_REPO)

    # Resolver el assignee (config explícita o el usuario logueado en `gh`).
    assignee = GITHUB_ASSIGNEE or _current_user_login()

    print(f"Deduplicando {len(tasks)} tarea(s) contra {len(existing)} issue(s) existente(s)...")
    to_create = dedupe_with_llm(existing, tasks)

    if not to_create:
        print("No se crearon tareas: todas ya existen en el panel.")
        return []

    created = []
    for t in to_create:
        title = t.get("title", "Sin título")
        body = t.get("description") or ""
        extra = []
        if t.get("issue_type"):
            extra.append(f"**Tipo:** {t['issue_type']}")
        if t.get("priority"):
            extra.append(f"**Prioridad:** {t['priority']}")
        if t.get("story_points"):
            extra.append(f"**Story points:** {t['story_points']}")
        if t.get("eta"):
            extra.append(f"**ETA:** {t['eta']}")
        if t.get("assignee"):
            extra.append(f"**Responsable:** {t['assignee']}")
        if t.get("session"):
            extra.append(f"**Reunión:** {t['session']}")
        if extra:
            body = (body + "\n\n---\n" + "\n".join(extra)).strip()

        try:
            issue = json.loads(
                _gh(["api", f"repos/{GITHUB_REPO}/issues", "-f", f"title={title}", "-f", f"body={body}"])
            )
        except SystemExit as e:
            print(f"  ✗ No se pudo crear: {title}\n    {e}")
            continue

        try:
            item_id = _add_to_project(project_id, issue["node_id"])
            url = issue.get("html_url", "")
            issue_number = issue.get("number")
            _assign_issue(GITHUB_REPO, issue_number, assignee)
            labels = _hashtags(title) or _hashtags(t.get("session") or "")
            if labels:
                _ensure_labels(GITHUB_REPO, labels)
                _apply_labels(GITHUB_REPO, issue_number, labels)
            if item_id:
                try:
                    _apply_item_fields(project_id, item_id, project_fields, t)
                except SystemExit as e:
                    print(f"  ⚠ Se creó el item pero falló al rellenar sus campos: {e}")
            print(f"  ✓ Creado y agregado al panel: {title}\n    {url}")
            created.append({**t, "github_url": url, "github_number": issue_number})
        except SystemExit as e:
            print(f"  ✓ Issue creado pero no se pudo agregar al panel: {title}\n    {e}")
            print(f"    {issue.get('html_url', '')}")

    return created


def attach_tags_to_tasks(tasks: list[dict], session: Path | None) -> None:
    """Publica helper: adjunta hashtags de la sesión a cada tarea (sin GitHub)."""
    for t in tasks:
        _attach_tags(t, session)
