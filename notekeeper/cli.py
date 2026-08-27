#!/usr/bin/env python3
"""Notekeeper - CLI para procesar reuniones grabadas."""
import argparse
import sys


def cmd_rec(args):
    from notekeeper.recorder import record, list_devices

    if args.list:
        list_devices()
        return

    print("=== Notekeeper - Grabar ===\n")
    mic = args.mic if args.mic else (True if args.add_mic else None)
    record(device=args.device, duration=args.duration, output=args.output, mic=mic)


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

    if args.session:
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
    list_recordings()


def cmd_show(args):
    from notekeeper.storage import list_sessions, get_session_dir, get_audio_path
    from notekeeper.search import format_full_transcript

    sessions = list_sessions()
    if not sessions:
        print("No hay grabaciones.")
        return

    if args.session:
        # Buscar por nombre parcial
        matches = [s for s in sessions if args.session in s.name]
        if not matches:
            print(f"No se encontró sesión: {args.session}")
            return
        session = matches[0]
    else:
        # Mostrar la más reciente
        session = sessions[0]

    print(format_full_transcript(session))


def cmd_search(args):
    from notekeeper.search import search_transcripts, format_results
    results = search_transcripts(args.query, limit=args.limit)
    print(format_results(results, args.query))


def cmd_skill(args):
    """Consulta con IA sobre las últimas reuniones transcritas."""
    from notekeeper.config import LLM_API_KEY
    from notekeeper.context import meetings_context

    query = " ".join(args.question)
    if not query:
        print("Especifica una pregunta.")
        return

    print(f"Consultando en las últimas {args.meetings} reuniones: \"{query}\"\n")
    context = meetings_context(limit=args.meetings)

    if not LLM_API_KEY:
        # Sin LLM, mostrar el contexto nomás
        print("=== Contexto encontrado ===\n")
        print(context[:2000])
        print("\n(Configura LLM_API_KEY para obtener respuesta con IA)")
        return

    # Llamada al LLM
    print("Consultando LLM...\n")
    answer = ask_llm(query, context)
    print("=== Respuesta ===\n")
    print(answer)


def ask_llm(question: str, context: str) -> str:
    """Llama al LLM con contexto de las transcripciones."""
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
        "Cita la sesión y el timestamp cuando sea posible."
    )

    user_prompt = f"Contexto de las reuniones:\n\n{context}\n\n---\nPregunta: {question}"

    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
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


def cmd_jira(args):
    from notekeeper.storage import list_sessions, get_transcript_text
    from notekeeper.tasks import run as run_jira
    from notekeeper.context import meetings_context, session_context

    sessions = list_sessions()
    if not sessions:
        print("No hay grabaciones.")
        return

    if args.session:
        matches = [s for s in sessions if args.session in s.name]
        if not matches:
            print(f"No se encontró sesión: {args.session}")
            return
        session = matches[0]
        if not get_transcript_text(session):
            print(f"{session.name} aún no está transcrita. Corre `notekeeper transcript` primero.")
            return
        context = session_context(session)
        label = session.name
    else:
        session = sessions[0]
        context = meetings_context(limit=args.meetings)
        label = f"últimas {args.meetings} reuniones"

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

    # transcript
    tr = sub.add_parser("transcript", help="Transcribir audios pendientes")
    tr.add_argument("-s", "--session", type=str, help="ID de sesión específica")

    # list
    sub.add_parser("list", help="Listar grabaciones")

    # show
    sh = sub.add_parser("show", help="Mostrar transcripción")
    sh.add_argument("session", nargs="?", help="ID de sesión (la más reciente si se omite)")

    # search
    se = sub.add_parser("search", help="Buscar en transcripciones")
    se.add_argument("query", help="Texto a buscar")
    se.add_argument("-n", "--limit", type=int, default=5, help="Máximo de resultados")

    # skill
    sk = sub.add_parser("skill", help="Preguntar con IA sobre las últimas reuniones")
    sk.add_argument("question", nargs="+", help="Pregunta a realizar")
    sk.add_argument("-n", "--meetings", type=int, default=10, help="Cuántas reuniones incluir (por defecto 10)")

    # jira
    ji = sub.add_parser("jira", help="Resumen + tareas Jira de las últimas reuniones")
    ji.add_argument("session", nargs="?", help="ID de sesión (las últimas 10 si se omite)")
    ji.add_argument("-n", "--meetings", type=int, default=10, help="Cuántas reuniones incluir (por defecto 10)")

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
        "jira": cmd_jira,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
