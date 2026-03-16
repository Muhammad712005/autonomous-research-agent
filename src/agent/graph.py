"""
LangGraph research graph — Phase 5.1: live LLM nodes.

Environment variables (load from .env via python-dotenv):
    GROQ_API_KEY   — required; get a free key at https://console.groq.com
    MODEL_NAME     — optional, defaults to llama-3.3-70b-versatile
    MAX_ITERATIONS — optional, defaults to 5
"""

import asyncio
import json
import logging
import operator
import os
from typing import Annotated, TypedDict

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from src.agent.schemas import generate_validated_report
from src.agent.tools import scrape_webpage, search_web  # noqa: F401

load_dotenv()

logger: logging.Logger = logging.getLogger(__name__)

_MAX_ITERATIONS: int = int(os.getenv("MAX_ITERATIONS", "3"))
_MODEL_NAME: str = os.getenv("MODEL_NAME", "llama-3.3-70b-versatile")

# ---------------------------------------------------------------------------
# LLM client — shared across all nodes in the process lifetime
# ---------------------------------------------------------------------------

_llm = ChatGroq(
    model=_MODEL_NAME,
    temperature=0.3,          # low temperature for structured / factual tasks
    max_tokens=4096,
)


# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------


class AgentState(TypedDict):
    """Shared state passed between every node in the research graph.

    Reducer rules:
    - `sub_tasks`: overwrite — manager and researcher replace the full queue.
    - `completed_tasks`: operator.add — accumulated across all iterations.
    - `raw_data`: operator.add — each researcher pass appends one entry.
    - `iteration_count`: operator.add — manager increments by 1 per planning
      cycle (new batch), 0 on passthrough (existing queue still being processed).
    - All other fields: last-write-wins (overwrite).
    """

    research_goal: str
    sub_tasks: list[str]
    completed_tasks: Annotated[list[str], operator.add]
    raw_data: Annotated[list[dict[str, str]], operator.add]
    final_report: dict[str, str] | str
    iteration_count: Annotated[int, operator.add]


# ---------------------------------------------------------------------------
# Node: Manager
# ---------------------------------------------------------------------------

_MANAGER_SYSTEM_PROMPT = """\
You are a senior research strategist. Your job is to break a high-level \
research goal into 2-3 concrete, actionable web-search queries that will \
surface the most relevant and up-to-date information.

You MUST respond with ONLY a valid JSON array of strings — no preamble, \
no explanation, no markdown fences.

Example output:
["query one here", "query two here", "query three here"]

Rules:
- Each query must be a specific, self-contained search string.
- Avoid queries already covered by completed tasks (listed below).
- Return between 2 and 3 queries, never more, never fewer.
"""


async def manager_node(state: AgentState) -> dict:
    """Planning node — generates new search queries via LLM when the queue is empty.

    Increments `iteration_count` by 1 only when a *new* planning cycle begins.
    Returns iteration_count=0 when tasks still remain so the counter stays
    accurate (prevents premature force-quit from execution steps being counted
    as planning cycles).
    """
    sub_tasks: list[str] = state["sub_tasks"]
    completed_tasks: list[str] = state["completed_tasks"]
    research_goal: str = state["research_goal"]

    if sub_tasks:
        logger.debug("manager_node: %d task(s) still in queue — passing through", len(sub_tasks))
        return {"iteration_count": 0}

    logger.info(
        "manager_node: generating new task batch for goal=%r (completed: %d)",
        research_goal,
        len(completed_tasks),
    )

    completed_summary = (
        "\n".join(f"- {t}" for t in completed_tasks)
        if completed_tasks
        else "None yet."
    )
    user_content = (
        f"Research goal: {research_goal}\n\n"
        f"Completed tasks (do NOT repeat these):\n{completed_summary}"
    )

    try:
        response = await _llm.ainvoke(
            [
                SystemMessage(content=_MANAGER_SYSTEM_PROMPT),
                HumanMessage(content=user_content),
            ]
        )
        raw: str = response.content  # type: ignore[union-attr]

        # Strip any accidental markdown fences
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        new_tasks: list[str] = json.loads(raw)
        if not isinstance(new_tasks, list) or not new_tasks:
            raise ValueError(f"Expected non-empty list, got: {new_tasks!r}")

        # Sanitise: ensure all items are strings
        new_tasks = [str(t).strip() for t in new_tasks if str(t).strip()]
        logger.info("manager_node: queued %d task(s): %s", len(new_tasks), new_tasks)

    except Exception as exc:
        logger.warning("manager_node: LLM call failed (%s) — using fallback tasks", exc)
        new_tasks = [
            f"{research_goal} overview",
            f"{research_goal} latest developments 2025",
            f"{research_goal} key examples",
        ]

    return {"sub_tasks": new_tasks, "iteration_count": 1}


# ---------------------------------------------------------------------------
# Node: Researcher
# ---------------------------------------------------------------------------

_RESEARCHER_SYSTEM_PROMPT = """\
You are a web research agent. You will be given a research query.
Your job is to find the single most relevant URL for that query and return \
ONLY that URL — no explanation, no markdown, just the raw URL string.

If you cannot determine a URL, return the string "NO_URL".
"""


async def _research_one_task(task: str) -> dict[str, str]:
    """Search the web for a single task, extract the best URL, and scrape it.

    Returns a raw_data entry dict with keys: task, content, source.
    Never raises — failures are captured as error strings so gather() keeps running.
    """
    try:
        # Step 1 — web search
        search_result: str = await search_web.ainvoke({"query": task})
        logger.debug("_research_one_task: search returned %d chars for %r", len(search_result), task)

        # Step 2 — extract the best URL from search results via LLM
        url_response = await _llm.ainvoke(
            [
                SystemMessage(content=_RESEARCHER_SYSTEM_PROMPT),
                HumanMessage(content=f"Query: {task}\n\nSearch results:\n{search_result}"),
            ]
        )
        candidate_url: str = url_response.content.strip()  # type: ignore[union-attr]

        # Step 3 — scrape the URL or fall back to search summary
        if candidate_url and candidate_url != "NO_URL" and candidate_url.startswith("http"):
            logger.info("_research_one_task: scraping URL=%r for task=%r", candidate_url, task)
            content: str = await scrape_webpage.ainvoke({"url": candidate_url})
            source: str = candidate_url
        else:
            logger.warning(
                "_research_one_task: no valid URL for task=%r — using search summary", task
            )
            content = search_result
            source = f"search:{task}"

        logger.info("_research_one_task: done task=%r (%d chars)", task, len(content))
        return {"task": task, "content": content, "source": source}

    except Exception as exc:  # noqa: BLE001
        logger.error("_research_one_task: failed task=%r: %s", task, exc, exc_info=True)
        return {"task": task, "content": f"[Research failed: {exc}]", "source": "error"}


async def researcher_node(state: AgentState) -> dict:
    """Execution node — processes ALL queued tasks concurrently via asyncio.gather.

    Processing all tasks in a single node pass (rather than one-at-a-time) cuts
    total wall-clock time from O(n*serial) to O(1*longest_task), trading slightly
    higher peak token usage for dramatically lower latency.

    Each task runs _research_one_task independently; failures are captured per-task
    so a single slow/broken site cannot block the rest of the batch.
    """
    sub_tasks: list[str] = state["sub_tasks"]
    logger.info("researcher_node: processing %d task(s) concurrently", len(sub_tasks))

    # Fan out — all tasks run in parallel on the same event loop
    entries: tuple[dict[str, str], ...] = await asyncio.gather(
        *(_research_one_task(task) for task in sub_tasks)
    )

    completed: list[str] = [e["task"] for e in entries]
    raw_data: list[dict[str, str]] = list(entries)

    logger.info("researcher_node: all %d task(s) complete", len(completed))
    return {
        "sub_tasks": [],        # queue fully consumed
        "completed_tasks": completed,
        "raw_data": raw_data,
    }


# ---------------------------------------------------------------------------
# Node: Writer
# ---------------------------------------------------------------------------


async def writer_node(state: AgentState) -> dict:
    """Synthesis node — compiles all raw_data into a validated Pydantic JSON report.

    Delegates to `generate_validated_report` from schemas.py which implements
    the 3-attempt error-correction loop with Pydantic validation.
    """
    raw_data: list[dict[str, str]] = state["raw_data"]
    research_goal: str = state["research_goal"]

    logger.info(
        "writer_node: synthesising %d data entries for goal=%r",
        len(raw_data),
        research_goal,
    )

    # generate_validated_report handles retries, validation, and fallback
    report_json: str = await generate_validated_report(
        llm_client=_llm,
        raw_data=raw_data,
    )

    logger.info("writer_node: report compiled successfully")
    return {"final_report": report_json}


# ---------------------------------------------------------------------------
# Conditional router
# ---------------------------------------------------------------------------


def route_manager(state: AgentState) -> str:
    """Determine whether to send work to the researcher or force-quit to the writer.

    Priority order:
    1. Hard limit: iteration_count >= _MAX_ITERATIONS → writer (prevents runaway loops)
    2. All tasks done: sub_tasks empty AND work has been completed → writer
    3. Default: route to researcher to process the next task
    """
    if state["iteration_count"] >= _MAX_ITERATIONS:
        logger.warning(
            "route_manager: iteration limit reached (%d/%d), routing to writer",
            state["iteration_count"],
            _MAX_ITERATIONS,
        )
        return "writer"

    if not state["sub_tasks"] and state["completed_tasks"]:
        logger.info(
            "route_manager: all tasks completed (%d total), routing to writer",
            len(state["completed_tasks"]),
        )
        return "writer"

    return "researcher"


# ---------------------------------------------------------------------------
# Graph compilation
# ---------------------------------------------------------------------------

_graph = StateGraph(AgentState)

_graph.add_node("manager", manager_node)
_graph.add_node("researcher", researcher_node)
_graph.add_node("writer", writer_node)

_graph.add_edge(START, "manager")
_graph.add_conditional_edges("manager", route_manager)  # returns "researcher" or "writer"
_graph.add_edge("researcher", "manager")
_graph.add_edge("writer", END)

research_graph = _graph.compile()
