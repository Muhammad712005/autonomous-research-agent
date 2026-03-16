"""
ResearchApp: Phase 3.2 — LangGraph backend wired to Textual TUI.

Threading model
---------------
LangGraph nodes are defined as `async` coroutines, so the graph must be
driven by an async event loop.  Textual's `@work(thread=True)` spins a
dedicated OS thread that owns its own `asyncio` event loop (via
`asyncio.run()`), keeping the entire multi-agent execution fully off the
Textual event loop.  All widget mutations are marshalled back through
`self.call_from_thread()`, which is the only thread-safe way to touch
Textual's widget tree from outside the main event loop.
"""

import asyncio
import logging

from textual import work
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, RichLog, Markdown
from textual.containers import Horizontal, Vertical

from src.agent.graph import research_graph, AgentState

logger = logging.getLogger(__name__)


class ResearchApp(App):
    """Keyboard-driven TUI control room for the Autonomous Web-Scraping Research Agent."""

    CSS_PATH = "styles.tcss"

    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("tab", "focus_next", "Next Pane"),
        ("shift+tab", "focus_previous", "Prev Pane"),
    ]

    TITLE = "Autonomous Research Agent"
    SUB_TITLE = "LangGraph · Playwright · Stealth"

    # ── Layout ────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Vertical(id="root"):
            with Horizontal(id="split-panes"):
                yield RichLog(
                    id="agent-log",
                    highlight=True,
                    markup=True,
                    wrap=True,
                )
                yield Markdown(
                    id="report-pane",
                    markdown="## Final Report\n\n*Waiting for research to complete...*",
                )

            yield Input(
                placeholder="Enter your research goal and press Enter…",
                id="goal-input",
            )

        yield Footer()

    def on_mount(self) -> None:
        """Focus the input immediately so the user can start typing."""
        self.query_one("#goal-input", Input).focus()

        log = self.query_one("#agent-log", RichLog)
        log.write("[bold #dc143c]◆ Research Agent online.[/bold #dc143c]")
        log.write("[dim]Type your research goal below and press Enter to begin.[/dim]")

    # ── Input event ──────────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Capture the user's goal and hand off to the background worker."""
        goal = event.value.strip()
        if not goal:
            return

        # Immediately clear and disable the input so the user cannot
        # submit a second goal while a run is already in progress.
        inp = self.query_one("#goal-input", Input)
        inp.value = ""
        inp.disabled = True

        log = self.query_one("#agent-log", RichLog)
        log.write(f"\n[bold]► Research goal:[/bold] {goal}")
        log.write("[dim]  Initialising agent graph…[/dim]")

        # Reset the report pane for a clean run
        self.call_after_refresh(
            self.query_one("#report-pane", Markdown).update,
            "## Final Report\n\n*Research in progress…*",
        )

        # Launch the heavy work in a background thread so the TUI stays live
        self.run_research_agent(goal)

    # ── Background worker ─────────────────────────────────────────────────────

    @work(thread=True, exclusive=True)
    def run_research_agent(self, goal: str) -> None:
        """Drive the LangGraph research graph in a dedicated OS thread.

        `thread=True` — runs this method in a ThreadPoolExecutor thread so the
        multi-agent scraping pipeline never touches the Textual event loop.

        `exclusive=True` — cancels any previously running worker before
        starting a new one, preventing concurrent graph executions.

        All widget updates use `self.call_from_thread()` which is the only
        thread-safe bridge back to the Textual event loop.
        """
        log = self.query_one("#agent-log", RichLog)
        report_pane = self.query_one("#report-pane", Markdown)

        # Convenience wrapper so callers don't repeat call_from_thread
        def ui_log(msg: str) -> None:
            self.call_from_thread(log.write, msg)

        def ui_report(markdown: str) -> None:
            self.call_from_thread(report_pane.update, markdown)

        def ui_enable_input() -> None:
            inp = self.query_one("#goal-input", Input)
            self.call_from_thread(setattr, inp, "disabled", False)
            self.call_from_thread(inp.focus)

        initial_state: AgentState = {
            "research_goal": goal,
            "sub_tasks": [],
            "completed_tasks": [],
            "raw_data": [],
            "final_report": "",
            "iteration_count": 0,
        }

        async def _stream_graph() -> dict:
            """Async inner coroutine — owns this thread's event loop entirely."""
            final_state: dict = {}

            # astream yields {node_name: state_update} after each node fires
            async for chunk in research_graph.astream(initial_state):
                for node_name, state_update in chunk.items():

                    if node_name == "manager":
                        tasks: list[str] = state_update.get("sub_tasks") or []
                        iteration: int = state_update.get("iteration_count", 0)
                        if tasks:
                            ui_log(
                                f"[bold #8b0000][Manager][/bold #8b0000] "
                                f"Cycle {iteration} — queued {len(tasks)} task(s):"
                            )
                            for t in tasks:
                                ui_log(f"  [dim]• {t}[/dim]")
                        else:
                            ui_log("[bold #8b0000][Manager][/bold #8b0000] Evaluating queue…")

                    elif node_name == "researcher":
                        completed: list[str] = state_update.get("completed_tasks") or []
                        remaining: list[str] = state_update.get("sub_tasks") or []
                        if completed:
                            ui_log(
                                f"[bold yellow][Researcher][/bold yellow] "
                                f"✓ Completed: [italic]{completed[-1]}[/italic] "
                                f"({len(remaining)} remaining)"
                            )

                    elif node_name == "writer":
                        ui_log("[bold green][Writer][/bold green] Synthesising final report…")
                        report = state_update.get("final_report")
                        if report:
                            final_state = state_update

            return final_state

        try:
            final_state = asyncio.run(_stream_graph())
        except Exception as exc:
            logger.exception("Graph execution failed: %s", exc)
            ui_log(f"\n[bold red]✗ Graph error:[/bold red] {exc}")
            ui_enable_input()
            return

        # ── Render the final report ───────────────────────────────────────────
        report = final_state.get("final_report", {})

        if isinstance(report, dict):
            title = report.get("goal", goal)
            summary = report.get("summary", "_No summary generated._")
            sources_raw = report.get("sources", "")
            sources_md = (
                "\n".join(f"- {s.strip()}" for s in sources_raw.split(",") if s.strip())
                if sources_raw
                else "_None recorded._"
            )
            markdown_output = (
                f"## {title}\n\n"
                f"### Executive Summary\n\n{summary}\n\n"
                f"### Sources\n\n{sources_md}"
            )
        elif isinstance(report, str) and report:
            markdown_output = report
        else:
            markdown_output = "## Report\n\n_No output was generated._"

        ui_report(markdown_output)
        ui_log("\n[bold #dc143c]◆ Research complete. Report loaded in right pane.[/bold #dc143c]")
        ui_enable_input()


if __name__ == "__main__":
    ResearchApp().run()
