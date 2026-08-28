#!/usr/bin/env python3
"""Notekeeper - CLI para procesar reuniones grabadas."""
import argparse
import sys
import re
import os


def _c(code: str) -> str:
    """Devuelve el código ANSI si la salida es un terminal (si no, vacío)."""
    if not sys.stdout.isatty():
        return ""
    return code


CYAN = _c("\033[36m")
GREEN = _c("\033[32m")
YELLOW = _c("\033[33m")
MAGENTA = _c("\033[35m")
BOLD = _c("\033[1m")
DIM = _c("\033[2m")
RESET = _c("\033[0m")


def extract_tags(args_list: list[str]) -> tuple[list[str], list[str]]:
    """Separa tokens `#tag` (p. ej. `#scotiabank`) del resto de los argumentos.

    Cada argumento puede contener varios tokens separados por espacios.
    Devuelve (tags, resto_de_argumentos).
    """
    tags = []
    rest = []
    for a in args_list:
        for tok in a.split():
            if re.fullmatch(r"#[\w\-]+", tok):
                tags.append(tok[1:])
            else:
                rest.append(tok)
    return tags, rest


def cmd_rec(args):
    from notekeeper.recorder import record, list_devices

    if args.list:
        list_devices()
        return

    print("=== Notekeeper - Grabar ===\n")
    mic = args.mic if args.mic else (True if args.add_mic else None)
    record(device=args.device, duration=args.duration, output=args.output, mic=mic, tags=args.tags)


def cmd_transcript(args):
    from notekeeper.transcriber import transcribe_file, format_transcript, load_model
    from notekeeper.storage import (
        find_untranscribed,
        save_transcript,
        save_metadata,
        load_metadata,
        get_audio_path,
        list_sessions,
    )

    if getattr(args, "tag", None) and not args.session:
        from notekeeper.storage import get_tags
        sessions = list_sessions(tags=[args.tag])
        untranscribed = []
        for session in sessions:
            audio = get_audio_path(session)
            if audio and not (session / "transcript.txt").exists():
                untranscribed.append((audio, session))
    elif args.session:
        # Transcribir una sesión específica
        from notekeeper.config import DATA_DIR
        session = DATA_DIR / args.session
        if not session.exists():
            print(f"Sesión no encontrada: {args.session}")
            sys.exit(1)
        audio = get_audio_path(session)
        if not audio:
            print(f"No hay audio en {session}")
            sys.exit(1)
        untranscribed = [(audio, session)]
    else:
        untranscribed = find_untranscribed()

    if not untranscribed:
        print("No hay audios sin transcribir.")
        return

    print(f"=== Notekeeper - Transcribir ({len(untranscribed)} archivos) ===\n")

    model = load_model()

    for audio_path, session in untranscribed:
        print(f"\n--- {session.name} ---")
        result = transcribe_file(audio_path, model=model)

        # Guardar
        transcript_text = format_transcript(result)
        save_transcript(session, transcript_text, result["segments"])
        save_metadata(session, {
            "language": result["language"],
            "segments_count": len(result["segments"]),
            "transcribed": True,
        })

        print(f"Guardado en {session.name}/transcript.txt")


def cmd_list(args):
    from notekeeper.recorder import list_recordings
    from notekeeper.storage import list_sessions, get_tags
    if getattr(args, "tag", None):
        tags = [args.tag]
    else:
        tags = getattr(args, "tags", None) or None
    sessions = list_sessions(tags=tags) if tags else None
    list_recordings(sessions=sessions)


def cmd_show(args):
    from notekeeper.storage import list_sessions, get_session_dir, get_audio_path
    from notekeeper.search import format_full_transcript

    tags, session_ids = extract_tags([args.session]) if args.session else ([], [])
    if getattr(args, "tag", None):
        tags.append(args.tag.lstrip("#"))
    sessions = list_sessions(tags=tags) if tags else list_sessions()
    if not sessions:
        print("No hay grabaciones.")
        return

    if session_ids:
        # Buscar por nombre parcial
        matches = [s for s in sessions if session_ids[0] in s.name]
        if not matches:
            print(f"No se encontró sesión: {session_ids[0]}")
            return
        session = matches[0]
    else:
        # Mostrar la más reciente
        session = sessions[0]

    print(format_full_transcript(session))


def cmd_search(args):
    from notekeeper.search import search_transcripts, format_results
    tags, query_words = extract_tags(args.query.split())
    query = " ".join(query_words)
    if not query:
        print("Especifica un texto a buscar.")
        return
    results = search_transcripts(query, limit=args.limit, tags=tags or None)
    print(format_results(results, query))


def cmd_tag(args):
    """Asigna o re-asigna tags/contexto a una o más sesiones."""
    from notekeeper.storage import list_sessions, get_session_dir, add_tags, get_tags

    if not args.tags:
        print("Indica al menos un tag. Uso: notekeeper tag <sesion|#tag> <tag>...")
        return

    sessions = None
    if getattr(args, "from_tag", None):
        from_tag = args.from_tag.lstrip("#")
        sessions = list_sessions(tags=[from_tag])
        if not sessions:
            print(f"No hay sesiones con el tag '{from_tag}'.")
            return
        print(f"Aplicando {args.tags} a {len(sessions)} sesión(es) con '{from_tag}'...")
    elif args.session and args.session.startswith("#"):
        # re-tagear todas las sesiones que ya tienen ese tag
        tag = args.session.lstrip("#")
        sessions = list_sessions(tags=[tag])
        if not sessions:
            print(f"No hay sesiones con el tag '{tag}'.")
            return
        print(f"Aplicando #{args.tags[0]} a {len(sessions)} sesión(es) con #{tag}...")
    elif args.session:
        target = args.session
        matches = [s for s in list_sessions() if target in s.name]
        if args.session in {s.name for s in list_sessions()}:
            matches = [get_session_dir(args.session)]
        if not matches:
            print(f"No se encontró sesión: {args.session}")
            return
        sessions = matches[:1]
    elif getattr(args, "all", False):
        sessions = list_sessions()
        print(f"Aplicando {args.tags} a TODAS las {len(sessions)} sesiones...")

    for s in sessions:
        all_tags = add_tags(s, args.tags)
        print(f"  {s.name}: tags = {', '.join(sorted(all_tags))}")

    if sessions:
        print("\nRecuerda reindexar embeddings si usas búsqueda semántica:")
        print("  python -m notekeeper embed-index --rebuild")


def cmd_skill(args):
    """Consulta con IA sobre las reuniones transcritas."""
    from notekeeper.config import LLM_API_KEY
    from notekeeper.context import meetings_context

    tags, question_words = extract_tags(args.question)
    query = " ".join(question_words)
    if not query:
        print("Especifica una pregunta.")
        return

    scope = f" (tags: {', '.join(tags)})" if tags else ""
    if getattr(args, "semantic", False):
        from notekeeper.embeddings import semantic_context, load_index
        if not (load_index().get("segments") or []):
            print("No hay índice de embeddings. Corre: python -m notekeeper embed-index")
            return
        print(f"Consulta semántica: \"{query}\"{scope}\n")
        print("Buscando fragmentos relevantes por embeddings...")
        context = semantic_context(query, tags=tags)
    else:
        print(f"Consultando en las últimas {args.meetings} reuniones{scope}: \"{query}\"\n")
        context = meetings_context(limit=args.meetings, tags=tags)

    if not LLM_API_KEY:
        # Sin LLM, mostrar el contexto nomás
        print("=== Contexto encontrado ===\n")
        print(context[:3000])
        print("\n(Configura LLM_API_KEY para obtener respuesta con IA)")
        return

    # Llamada al LLM
    print("Consultando LLM...\n")
    answer = ask_llm(query, context)
    print("=== Respuesta ===\n")
    print(answer)


def cmd_chat(args):
    """Chat interactivo con IA sobre las reuniones (con memoria de conversación)."""
    from notekeeper.config import LLM_API_KEY

    tags, question_words = extract_tags(args.question) if args.question else ([], [])
    if getattr(args, "tag", None):
        tags.append(args.tag.lstrip("#"))
    initial = " ".join(question_words)
    semantic = getattr(args, "semantic", False)
    meetings = getattr(args, "meetings", 10)

    scope = f"[contexto: {', '.join(tags)}]" if tags else "[todas las reuniones]"
    print(f"{BOLD}=== Chat sobre tus grabaciones {scope} ==={RESET}")
    print(f"{DIM}Escribe tu pregunta; 'salir', 'exit' o 'quit' (o Ctrl-C) para terminar.{RESET}\n")

    history: list[dict] = []
    question = initial

    while True:
        if not question:
            try:
                question = input(f"{CYAN}{BOLD}tú>{RESET} ").strip()
            except (KeyboardInterrupt, EOFError):
                print(f"\n{YELLOW}Adiós.{RESET}")
                break
            if not question:
                continue
            if question.lower() in ("salir", "salí", "exit", "quit", "q", ":q"):
                print(f"{YELLOW}Adiós.{RESET}")
                break

        # Recuperar contexto según el modo
        if semantic:
            from notekeeper.embeddings import semantic_context, load_index
            if not (load_index().get("segments") or []):
                print("No hay índice de embeddings. Corre: python -m notekeeper embed-index")
                return
            context = semantic_context(question, tags=tags)
        else:
            from notekeeper.context import meetings_context
            context = meetings_context(limit=meetings, tags=tags)

        if not LLM_API_KEY:
            print("=== Contexto encontrado (sin LLM) ===\n")
            print(context[:3000])
            print("\n(Configura LLM_API_KEY para obtener respuesta con IA)")
        else:
            print(f"{DIM}consultando...{RESET}")
            answer = ask_llm(question, context, history=history)
            print(f"{GREEN}{BOLD}asistente>{RESET} {answer}\n")
            history.append({"role": "user", "content": question})
            history.append({"role": "assistant", "content": answer})

        question = ""


def cmd_embed_index(args):
    from notekeeper.embeddings import index_sessions, load_index

    if args.list:
        index = load_index()
        segs = index.get("segments") or []
        print(f"Índice: {index.get('provider', '?')} / {index.get('model', '?')}")
        print(f"Segmentos indexados: {len(segs)}")
        return

    index_sessions(force=args.rebuild)


def cmd_diarize(args):
    from notekeeper.storage import list_sessions, load_metadata
    from notekeeper.config import DATA_DIR
    from notekeeper.diarizer import diarize_session, map_speaker_names, speaker_label
    from notekeeper.embeddings import index_sessions

    if args.session:
        session_dir = DATA_DIR / args.session
        if not session_dir.exists():
            matches = [s for s in list_sessions() if args.session in s.name]
            if not matches:
                print(f"No se encontró sesión: {args.session}")
                return
            session_dir = matches[0]
        sessions = [session_dir]
    elif getattr(args, "tag", None):
        sessions = list_sessions(tags=[args.tag])
    else:
        sessions = list_sessions()

    if not sessions:
        print("No hay grabaciones.")
        return

    diarized = 0
    skipped = 0
    for s in sessions:
        if not (s / "segments.json").exists():
            print(f"{s.name}: aún no está transcrita; se omite.")
            continue
        meta = load_metadata(s)
        if not args.force and meta.get("diarized"):
            print(f"{s.name}: ya diarizada; usa --force para re-diariazar.")
            skipped += 1
            continue
        counts = diarize_session(s, verbose=True)
        if not counts:
            continue
        for spk, n in counts:
            print(f"  - {speaker_label(s, spk)}: {n} segmentos")
        if args.names:
            map_speaker_names(s, counts)
        diarized += 1

    print(f"\n{diarized} sesión(es) diarizada(s)"
          + (f", {skipped} ya estaban diarizada(s)" if skipped else "") + ".")
    print("Corre `python -m notekeeper embed-index --rebuild` para que los "
          "hablantes entren al índice de embeddings.")
    if args.reindex:
        print("Reindexando embeddings...")
        index_sessions(force=True)


def ask_llm(question: str, context: str, history: list[dict] | None = None) -> str:
    """Llama al LLM con contexto de las transcripciones.

    ``history`` es una lista opcional de mensajes previos ``{"role", "content"}``
    (conversación anterior) para dar memoria al chat.
    """
    from notekeeper.config import LLM_API_KEY, LLM_MODEL, LLM_BASE_URL

    try:
        from openai import OpenAI
    except ImportError:
        return "Error: instala openai (`pip install openai`)"

    client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)

    system_prompt = (
        "Eres un asistente que responde preguntas sobre reuniones grabadas. "
        "Usa SOLO la información del contexto proporcionado. "
        "Si la información no está en el contexto, di que no la encontraste. "
        "Cita la sesión y el timestamp cuando sea posible. "
        "Puedes apoyarte en la conversación previa para responder seguimientos."
    )

    user_prompt = f"Contexto de las reuniones:\n\n{context}\n\n---\nPregunta: {question}"

    messages = [{"role": "system", "content": system_prompt}]
    for m in history or []:
        if m.get("role") in ("user", "assistant"):
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": user_prompt})

    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=0.3,
            max_tokens=1024,
            extra_headers={
                "HTTP-Referer": "https://github.com/sightes/meeting-ai",
                "X-Title": "notekeeper",
            },
        )
    except Exception as exc:
        return (
            f"Error llamando al LLM: {exc}. "
            "Si es por límite de modelo free, reintenta o cambia LLM_MODEL en .env."
        )

    choices = getattr(response, "choices", None)
    if not choices or not getattr(choices[0], "message", None):
        return "(el modelo no devolvió una respuesta; reintenta o cambia LLM_MODEL en .env)"

    message = choices[0].message
    content = getattr(message, "content", None)
    if not content:
        content = getattr(message, "reasoning_content", None) or ""
    if not content:
        return "(el modelo devolvió una respuesta vacía; reintenta o cambia LLM_MODEL en .env)"
    return content


def _format_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _is_date(value: str) -> bool:
    """True si el valor tiene forma de fecha YYYY-MM-DD."""
    import re

    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value))


def cmd_jira(args):
    from notekeeper.storage import list_sessions, get_transcript_text, get_tags
    from notekeeper.tasks import run as run_jira
    from notekeeper.context import meetings_context, session_context

    tags, session_ids = extract_tags([args.session]) if args.session else ([], [])
    if getattr(args, "tags", None):
        tags.extend(t.strip().lstrip("#") for t in args.tags if t.strip())
    sessions = list_sessions(tags=tags) if tags else list_sessions()
    if not sessions:
        print("No hay grabaciones.")
        return

    session = None
    if session_ids:
        target = session_ids[0]
        # Si es una fecha (YYYY-MM-DD), elegir la última transcripción de ese día.
        if _is_date(target):
            matches = [s for s in sessions if s.name.startswith(target)]
            if not matches:
                print(f"No se encontró transcripción para la fecha: {target}")
                return
            # list_sessions() ya ordena de más reciente a más antigua.
            session = matches[0]
        else:
            matches = [s for s in sessions if target in s.name]
            if not matches:
                print(f"No se encontró sesión: {target}")
                return
            session = matches[0]
        if not get_transcript_text(session):
            print(f"{session.name} aún no está transcrita. Corre `notekeeper transcript` primero.")
            return
        label = session.name
    elif tags:
        session = sessions[0]
        label = f"últimas {args.meetings} reuniones (tags: {', '.join(tags)})"
    else:
        session = sessions[0]
        label = f"últimas {args.meetings} reuniones"

    if getattr(args, "embeddings", False):
        from notekeeper.embeddings import tasks_semantic_context, load_index
        if not (load_index().get("segments") or []):
            print("No hay índice de embeddings. Corre primero: python -m notekeeper embed-index")
            return
        print(f"=== Notekeeper - Jira con embeddings ({label}) ===\n")
        print("Recuperando fragmentos relevantes por similitud semántica...")
        context = tasks_semantic_context(
            session=session.name if session_ids else None,
            tags=tags or None,
        )
    else:
        if session_ids:
            context = session_context(session)
        else:
            context = meetings_context(limit=args.meetings, tags=tags or None)
        print(f"=== Notekeeper - Jira ({label}) ===\n")

    data = run_jira(context, session)

    from notekeeper.tasks import render_summary, render_tasks, render_meetings

    print(render_summary(data))
    print()
    mapeo = render_meetings(data)
    if mapeo:
        print(mapeo)
        print()
    print(render_tasks(data))
    print("Guardado: tasks.json, jira_tasks.csv, meeting_summary.txt en", session.name)

    # Enviar tareas al panel de GitHub Projects (si está configurado).
    from notekeeper import github_projects
    if github_projects.enabled():
        print("\n=== Sincronizando tareas con GitHub Projects ===")
        print()
        github_projects.sync_tasks(data.get("tasks") or [], session)


def cmd_resume(args):
    """Genera los .md de resumen para todas las reuniones resumidas."""
    from notekeeper.summarize import resume_all

    print("=== Notekeeper - Resume ===")
    resume_all()


def cmd_backfill(args):
    """Rellena los campos (Priority/Size/Estimate/fechas) de las tareas ya en el panel."""
    from notekeeper import github_projects
    github_projects.backfill_item_fields()


def cmd_describe_fields(args):
    """Genera y fija descripciones de las opciones (columnas) de los campos del panel."""
    from notekeeper import github_projects
    github_projects.describe_fields(force=args.force, dry_run=args.dry_run)


def main():
    parser = argparse.ArgumentParser(
        prog="notekeeper",
        description="CLI para procesar reuniones grabadas",
    )
    sub = parser.add_subparsers(dest="command", help="Comandos disponibles")

    # rec
    rec = sub.add_parser("rec", help="Grabar audio")
    rec.add_argument("-t", "--duration", type=int, help="Duración en segundos")
    rec.add_argument("-d", "--device", type=str, help="Índice o nombre del dispositivo (p. ej. 10 o 'BlackHole 2ch')")
    rec.add_argument("-m", "--add-mic", action="store_true", help="Mezclar micrófono + audio de sistema (reunión completa)")
    rec.add_argument("--mic", type=str, help="Dispositivo de micrófono para la mezcla (índice o nombre)")
    rec.add_argument("-l", "--list", action="store_true", help="Listar dispositivos")
    rec.add_argument("-o", "--output", type=str, help="Nombre de sesión de salida")
    rec.add_argument("--tags", nargs="+", help="Tags/contextos de la reunión (p. ej. scotiabank proyecto-x)")

    # transcript
    tr = sub.add_parser("transcript", help="Transcribir audios pendientes")
    tr.add_argument("-s", "--session", type=str, help="ID de sesión específica")
    tr.add_argument("--tag", type=str, help="Solo transcribir sesiones con este tag")

    # list
    li = sub.add_parser("list", help="Listar grabaciones")
    li.add_argument("--tag", type=str, help="Filtrar por tag/contexto")

    # show
    sh = sub.add_parser("show", help="Mostrar transcripción")
    sh.add_argument("session", nargs="?", help="ID de sesión (la más reciente si se omite)")
    sh.add_argument("--tag", type=str, help="Filtrar por tag/contexto (con # o sin)")

    # search
    se = sub.add_parser("search", help="Buscar en transcripciones")
    se.add_argument("query", help="Texto a buscar")
    se.add_argument("-n", "--limit", type=int, default=5, help="Máximo de resultados")

    # skill
    sk = sub.add_parser("skill", help="Preguntar con IA sobre las últimas reuniones")
    sk.add_argument("question", nargs="+", help="Pregunta a realizar")
    sk.add_argument("-n", "--meetings", type=int, default=10, help="Cuántas reuniones incluir (por defecto 10)")
    sk.add_argument("-s", "--semantic", action="store_true", help="Usar búsqueda semántica por embeddings (requiere índice)")

    # chat
    ch = sub.add_parser("chat", help="Chat interactivo con IA sobre las reuniones (con memoria)")
    ch.add_argument("question", nargs="*", help="Pregunta inicial (opcional; luego modo interactivo)")
    ch.add_argument("-n", "--meetings", type=int, default=10, help="Cuántas reuniones incluir por turno (por defecto 10)")
    ch.add_argument("-s", "--semantic", action="store_true", help="Usar búsqueda semántica por embeddings (requiere índice)")
    ch.add_argument("--tag", type=str, help="Filtrar por tag/contexto (con # o sin)")

    # embed-index
    ei = sub.add_parser("embed-index", help="Indexar transcripciones para búsqueda semántica (embeddings)")
    ei.add_argument("--rebuild", action="store_true", help="Regenerar el índice desde cero")
    ei.add_argument("-l", "--list", action="store_true", help="Mostrar info del índice")

    # diarize
    dz = sub.add_parser("diarize", help="Identificar hablantes con pyannote (requiere HF_TOKEN)")
    dz.add_argument("session", nargs="?", help="ID de sesión (todas con transcripción si se omite)")
    dz.add_argument("--tag", type=str, help="Solo diarizar sesiones con este tag")
    dz.add_argument("-n", "--names", action="store_true", help="Pedir el nombre real de cada hablante")
    dz.add_argument("-r", "--reindex", action="store_true", help="Reindexar embeddings al terminar")
    dz.add_argument("-f", "--force", action="store_true", help="Re-diariazar aunque ya esté diarizada")

    # jira
    ji = sub.add_parser("jira", help="Resumen + tareas Jira de las últimas reuniones")
    ji.add_argument("session", nargs="?", help="ID de sesión o #tag (las últimas 10 si se omite)")
    ji.add_argument("-n", "--meetings", type=int, default=10, help="Cuántas reuniones incluir (por defecto 10)")
    ji.add_argument("-e", "--embeddings", action="store_true", help="Usar búsqueda semántica por embeddings (requiere índice)")
    ji.add_argument("--tags", nargs="+", help="Tags/contextos (p. ej. scotiabank); también acepta el prefijo # en session")

    # tag
    tg = sub.add_parser("tag", help="Asignar tags/contexto a una sesión")
    tg.add_argument("session", nargs="?", help="ID de sesión (o '--all' / '--from-tag' para varias)")
    tg.add_argument("tags", nargs="+", help="Tags/contextos a asignar (p. ej. scotiabank)")
    tg.add_argument("--all", action="store_true", help="Aplicar a todas las sesiones")
    tg.add_argument("--from-tag", type=str, help="Aplicar a todas las sesiones que ya tengan este tag")

    # resume
    rs = sub.add_parser("resume", help="Generar los .md de resumen de todas las reuniones resumidas")
    rs.add_argument("--all", action="store_true", help="(reservado) procesar también sesiones sin resumen")

    # backfill
    bf = sub.add_parser("backfill", help="Rellenar campos de las tareas ya existentes en GitHub Projects")

    # describe-fields
    df = sub.add_parser("describe-fields", help="Generar y fijar descripciones de las opciones (columnas) de los campos del panel GitHub Projects")
    df.add_argument("-f", "--force", action="store_true", help="Regenerar descripciones aunque ya existan")
    df.add_argument("-d", "--dry-run", action="store_true", help="Mostrar las descripciones sin aplicarlas a GitHub")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "rec": cmd_rec,
        "transcript": cmd_transcript,
        "list": cmd_list,
        "show": cmd_show,
        "search": cmd_search,
        "skill": cmd_skill,
        "chat": cmd_chat,
        "embed-index": cmd_embed_index,
        "diarize": cmd_diarize,
        "jira": cmd_jira,
        "tag": cmd_tag,
        "resume": cmd_resume,
        "backfill": cmd_backfill,
        "describe-fields": cmd_describe_fields,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
