"""Interfaz TUI para el chat interactivo (estilo opencode).

Se lanza desde ``cmd_chat`` en ``cli.py``.  Reutiliza ``ask_llm``,
``meetings_context`` y ``semantic_context`` tal cual.
"""
from __future__ import annotations

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import var
from textual.widgets import Footer, Header, Input, RichLog, Static


class StatusBar(Static):
    """Barra inferior con info del modelo y modo."""

    def __init__(self, model: str, mode: str, **kwargs):
        super().__init__(**kwargs)
        self._model = model
        self._mode = mode

    def compose(self) -> ComposeResult:
        yield Static(
            f"[dim]{self._model}[/]  [bold]{self._mode}[/]",
            id="status-text",
        )


class NotekeeperChatApp(App):
    """App TUI para chat con IA sobre reuniones grabadas."""

    CSS = """
    Screen {
        layout: vertical;
    }
    #conversation {
        height: 1fr;
        margin: 0 1;
        padding: 0 1;
    }
    #input-area {
        height: auto;
        padding: 0 1;
        margin: 0 1;
    }
    #input-area Input {
        background: $surface;
        border: tall $primary;
    }
    #status-bar {
        height: 1;
        background: $primary-background-lighten-2;
        color: $text;
        padding: 0 2;
    }
    #status-text {
        width: 100%;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Salir", show=True),
        Binding("ctrl+l", "clear", "Limpiar", show=True),
    ]

    TITLE = "Notekeeper Chat"

    def __init__(
        self,
        semantic: bool = False,
        tags: list[str] | None = None,
        meetings: int = 10,
        initial: str = "",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.semantic = semantic
        self.tags = tags or []
        self.meetings = meetings
        self.initial = initial
        self.history: list[dict] = []
        self._model = self._get_model_name()

    def _get_model_name(self) -> str:
        from notekeeper.config import LLM_MODEL, EMBEDDING_PROVIDER, EMBEDDING_MODEL

        return LLM_MODEL.split("/")[-1] if "/" in LLM_MODEL else LLM_MODEL

    def compose(self) -> ComposeResult:
        mode = "embeddings" if self.semantic else "todas las reuniones"
        if self.tags:
            mode += f" [{', '.join(self.tags)}]"

        yield Header()
        yield RichLog(id="conversation", markup=True, wrap=True, highlight=True)
        yield Vertical(
            Input(placeholder="Escribe tu pregunta...", id="query-input"),
            id="input-area",
        )
        yield StatusBar(self._model, mode, id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one("#conversation", RichLog)
        scope = ", ".join(self.tags) if self.tags else "todas las reuniones"
        log.write(f"[bold cyan]Chat sobre reuniones[/] [dim]({scope})[/]\n")
        log.write("[dim]Escribe tu pregunta; Ctrl+C para salir.[/]\n")
        self.query_one("#query-input", Input).focus()

        if self.initial:
            self.query_one("#query-input", Input).value = self.initial
            self._send_question(self.initial)

    @on(Input.Submitted, "#query-input")
    def on_input_submitted(self, event: Input.Submitted) -> None:
        question = event.value.strip()
        if not question:
            return
        event.input.value = ""
        self._send_question(question)

    def _send_question(self, question: str) -> None:
        if question.lower() in ("salir", "salí", "exit", "quit", "q", ":q"):
            self.exit()
            return

        log = self.query_one("#conversation", RichLog)
        log.write(f"[bold green]tú>[/] {question}\n")

        self._call_llm(question)

    @work(thread=True)
    def _call_llm(self, question: str) -> None:
        from notekeeper.config import LLM_API_KEY

        log = self.query_one("#conversation", RichLog)

        if not LLM_API_KEY:
            log.write(
                "[yellow]Configura LLM_API_KEY en .env para usar IA.[/]\n"
            )
            return

        # Construir contexto
        if self.semantic:
            from notekeeper.embeddings import semantic_context, load_index

            index = load_index()
            if not (index.get("segments") or []):
                log.write(
                    "[red]No hay índice de embeddings. "
                    "Corre: python -m notekeeper embed-index[/]\n"
                )
                return
            context = semantic_context(question, tags=self.tags)
        else:
            from notekeeper.context import meetings_context

            context = meetings_context(limit=self.meetings, tags=self.tags)

        # Llamar al LLM (desde thread para no bloquear la UI)
        from notekeeper.cli import ask_llm

        answer = ask_llm(question, context, history=self.history)

        self.history.append({"role": "user", "content": question})
        self.history.append({"role": "assistant", "content": answer})

        self.call_from_thread(self._display_answer, answer)

    def _display_answer(self, answer: str) -> None:
        log = self.query_one("#conversation", RichLog)
        log.write(f"[bold cyan]asistente>[/] {answer}\n")

    def action_clear(self) -> None:
        log = self.query_one("#conversation", RichLog)
        log.clear()
        log.write("[dim]Conversación limpiada.[/]\n")
