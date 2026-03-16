"""
FastAPI WebSocket server — Phase 3.1

Architecture
------------
The LangGraph graph is fully async, so we stream its execution directly from
the WebSocket handler coroutine.  Each node completion emits a JSON ``log``
frame so the frontend can display live progress without polling.  The final
``result`` frame is sent once the graph reaches END.

Wire protocol (server → client)
--------------------------------
  {"type": "log",    "agent": "<node_name>", "message": "<human-readable>"}
  {"type": "result", "data": <final_report>}
  {"type": "error",  "message": "<reason>"}

Starting the server
-------------------
  python -m src.api.server
  # or:
  uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload
"""

import json
import logging
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from src.agent.graph import AgentState, research_graph

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App initialisation
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Autonomous Research Agent API",
    description="LangGraph-powered multi-agent research orchestrator with WebSocket streaming.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # tighten to specific origins before production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_log(agent: str, message: str) -> str:
    """Serialise a progress frame."""
    return json.dumps({"type": "log", "agent": agent, "message": message})


def _make_result(data: Any) -> str:
    """Serialise the final report frame."""
    return json.dumps({"type": "result", "data": data})


def _make_error(message: str) -> str:
    """Serialise an error frame."""
    return json.dumps({"type": "error", "message": message})


def _format_log_for_node(node_name: str, state_update: dict) -> list[str]:
    """Translate a raw LangGraph state-update dict into human-readable log lines.

    Returns a list so a single node transition can emit multiple frames
    (e.g., one per task queued by the Manager).
    """
    messages: list[str] = []

    if node_name == "manager":
        tasks: list[str] = state_update.get("sub_tasks") or []
        iteration: int = state_update.get("iteration_count", 0)
        if tasks:
            messages.append(
                f"Planning cycle {iteration}: queued {len(tasks)} task(s)."
            )
            for task in tasks:
                messages.append(f"  • {task}")
        else:
            messages.append("Re-evaluating task queue…")

    elif node_name == "researcher":
        completed: list[str] = state_update.get("completed_tasks") or []
        remaining: list[str] = state_update.get("sub_tasks") or []
        if completed:
            messages.append(
                f"Completed: \"{completed[-1]}\" ({len(remaining)} task(s) remaining)."
            )

    elif node_name == "writer":
        messages.append("All tasks done. Synthesising final report…")

    else:
        # Unknown / future nodes — emit a generic frame
        messages.append(f"Node '{node_name}' executed.")

    return messages


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@app.websocket("/ws/research")
async def research_ws(websocket: WebSocket) -> None:
    """Stream LangGraph agent execution over a persistent WebSocket connection.

    Protocol
    --------
    1. Client connects and sends the research goal as a plain-text message.
    2. Server streams ``log`` frames as each graph node fires.
    3. Server sends a single ``result`` frame when the graph reaches END.
    4. Connection is closed cleanly by the server after the result is sent,
       or with an ``error`` frame if an unrecoverable exception is raised.
    """
    await websocket.accept()
    logger.info("WebSocket connection accepted from %s", websocket.client)

    try:
        # ── 1. Receive the research goal ─────────────────────────────────────
        goal: str = (await websocket.receive_text()).strip()
        if not goal:
            await websocket.send_text(_make_error("Research goal must not be empty."))
            await websocket.close(code=1003)
            return

        logger.info("Research goal received: %r", goal)
        await websocket.send_text(
            _make_log("system", f"Research goal accepted: \"{goal}\"")
        )

        # ── 2. Build initial state ────────────────────────────────────────────
        initial_state: AgentState = {
            "research_goal": goal,
            "sub_tasks": [],
            "completed_tasks": [],
            "raw_data": [],
            "final_report": "",
            "iteration_count": 0,
        }

        # ── 3. Stream the graph ───────────────────────────────────────────────
        final_report: Any = None

        async for chunk in research_graph.astream(initial_state):
            # chunk → {node_name: state_update_dict}
            for node_name, state_update in chunk.items():
                log_lines = _format_log_for_node(node_name, state_update)
                for line in log_lines:
                    await websocket.send_text(_make_log(node_name, line))

                # Capture the report whenever the writer node fires
                if node_name == "writer":
                    final_report = state_update.get("final_report")

        # ── 4. Send the final result ──────────────────────────────────────────
        if final_report is None:
            await websocket.send_text(
                _make_error("Graph completed but produced no final report.")
            )
        else:
            await websocket.send_text(_make_result(final_report))
            logger.info("Final report sent to client.")

        await websocket.send_text(
            _make_log("system", "Research complete. Connection closing.")
        )
        await websocket.close(code=1000)

    except WebSocketDisconnect as exc:
        logger.warning("Client disconnected early (code=%s).", exc.code)

    except Exception as exc:
        logger.exception("Unhandled error during graph execution: %s", exc)
        try:
            await websocket.send_text(_make_error(f"Internal error: {exc}"))
            await websocket.close(code=1011)
        except Exception:
            pass  # socket may already be closed


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    """Simple liveness probe — confirms the server is accepting connections."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "src.api.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,               # hot-reload on file changes during development
        log_level="info",
    )
