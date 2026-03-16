import json
import logging
import pathlib
import re
from datetime import datetime

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError

logger: logging.Logger = logging.getLogger(__name__)

_MAX_VALIDATION_RETRIES: int = 3
_LOGS_DIR: pathlib.Path = pathlib.Path(".logs")

# ---------------------------------------------------------------------------
# JSON fence regex — strips ```json ... ``` and ``` ... ``` wrappers that
# LLMs commonly emit around structured outputs.
# ---------------------------------------------------------------------------
_JSON_FENCE_RE: re.Pattern[str] = re.compile(
    r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class ResearchReport(BaseModel):
    """Professional intelligence-briefing output schema for the Writer agent.

    Every field is required. The LLM must produce a JSON object matching this
    schema exactly — any missing or incorrectly typed field will raise a
    ValidationError and trigger a correction retry.

    Field-level descriptions are intentionally verbose so that
    ``model_json_schema()`` produces self-explanatory instructions that can
    be injected directly into the Writer system prompt.
    """

    title: str = Field(
        description=(
            "A precise, authoritative title for the intelligence report. "
            "Must read like a professional whitepaper heading — specific, not generic. "
            "No trailing punctuation."
        )
    )
    abstract: str = Field(
        description=(
            "A strong 2–3 sentence executive abstract that immediately communicates "
            "the scope, significance, and key conclusion of the research. "
            "Written for a senior decision-maker who may read nothing else."
        )
    )
    comprehensive_analysis: str = Field(
        description=(
            "The core body of the report. Write at least 3–4 well-structured, "
            "detailed paragraphs that synthesise ALL collected data into coherent, "
            "professional prose. Do NOT use bullet points here — use flowing paragraphs. "
            "Use markdown subheadings (###) to separate major themes or sections. "
            "Cite specific facts and figures extracted from the sources. "
            "This field must demonstrate deep analytical insight, not surface-level summary."
        )
    )
    strategic_takeaways: list[str] = Field(
        description=(
            "3–5 high-level strategic bullet points distilling the most actionable "
            "or significant insights from the analysis. Each item must be a complete, "
            "standalone statement that delivers a concrete takeaway. "
            "Minimum 3 items required."
        )
    )
    primary_sources: list[str] = Field(
        description=(
            "A list of URLs that directly contributed content to this report. "
            "Each entry must be a fully-qualified URL including the scheme "
            "(e.g. 'https://example.com/article'). "
            "Minimum 1 entry required."
        )
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _extract_json(text: str) -> str:
    """Strip markdown code fences from an LLM response and return raw JSON text.

    LLMs often wrap JSON in ```json ... ``` or ``` ... ``` blocks. This helper
    extracts the inner content so Pydantic can parse it directly.
    Falls back to returning the stripped raw text when no fences are detected.
    """
    match = _JSON_FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


def _cache_report(report_json: str) -> None:
    """Write a final report JSON string to .logs/ for post-mortem debugging.

    Non-fatal — a write failure is logged as a warning and silently skipped
    so that the caller's return value is never affected.
    """
    try:
        _LOGS_DIR.mkdir(exist_ok=True)
        timestamp: str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path: pathlib.Path = _LOGS_DIR / f"final_report_{timestamp}.json"
        path.write_text(report_json, encoding="utf-8")
        logger.debug("Final report cached to %s", path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to cache final report: %s", exc)


def _format_raw_data(raw_data: list[dict[str, str]]) -> str:
    """Serialize AgentState raw_data into a structured prompt string.

    Each entry in raw_data contains {"task": ..., "content": ...} as produced
    by researcher_node. This helper formats them into human-readable sections
    so the LLM can clearly associate content with its originating task.
    """
    sections: list[str] = [
        f"## Task: {entry.get('task', 'Unknown')}\n\n{entry.get('content', '').strip()}"
        for entry in raw_data
    ]
    return "\n\n---\n\n".join(sections)


# ---------------------------------------------------------------------------
# Validation loop
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE: str = """\
You are an expert intelligence analyst and professional long-form writer. \
Your task is to synthesise the provided research data into a structured, \
authoritative JSON report that reads like a published intelligence briefing.

You MUST respond with ONLY a valid JSON object — no preamble, no explanation, \
no markdown fences. The JSON must exactly match this schema:

{schema}

Rules:
- Every field is required. Do not omit any key.
- `comprehensive_analysis` must contain at minimum 3 full paragraphs of analytical \
  prose separated by markdown subheadings (###). Do NOT use bullet points inside it.
- `strategic_takeaways` must be a JSON array of strings (minimum 3 items).
- `primary_sources` must be a JSON array of fully-qualified URL strings (minimum 1 item).
- Do NOT use generic filler phrases like "It is important to note" or \
  "In conclusion". Write with authority and precision.
- Do not add extra keys beyond those defined in the schema.
"""


async def generate_validated_report(
    llm_client: BaseChatModel,
    raw_data: list[dict[str, str]],
) -> str:
    """Attempt to generate and validate a ResearchReport JSON from raw research data.

    Accepts the ``raw_data`` list directly from ``AgentState`` (as produced by
    ``researcher_node`` in ``graph.py``) — each element is a ``dict[str, str]``
    with ``task`` and ``content`` keys.

    Implements an error-correction loop: if the LLM's output fails Pydantic
    validation, the exact error message is fed back into the next prompt so the
    model can self-correct. Retries up to ``_MAX_VALIDATION_RETRIES`` times
    before returning a structured fallback to keep the pipeline alive.

    Args:
        llm_client: A ``BaseChatModel`` instance (e.g. ``ChatAnthropic``).
        raw_data:   The accumulated research entries from ``AgentState["raw_data"]``.

    Returns:
        A JSON string representing a valid ``ResearchReport``, or a fallback
        JSON string on total validation failure.
    """
    schema_str: str = json.dumps(ResearchReport.model_json_schema(), indent=2)
    system_prompt: str = _SYSTEM_PROMPT_TEMPLATE.format(schema=schema_str)
    formatted_data: str = _format_raw_data(raw_data)
    error_context: str = ""

    for attempt in range(1, _MAX_VALIDATION_RETRIES + 1):
        user_content: str = formatted_data
        if error_context:
            user_content += (
                f"\n\n---\n\nYour previous output failed validation with this error:\n"
                f"{error_context}\n\n"
                f"Fix the JSON and try again. Return ONLY the corrected JSON object."
            )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ]

        logger.info(
            "generate_validated_report: attempt %d/%d",
            attempt,
            _MAX_VALIDATION_RETRIES,
        )

        try:
            response = await llm_client.ainvoke(messages)
            raw_output: str = response.content  # type: ignore[union-attr]
            json_text: str = _extract_json(raw_output)

            report: ResearchReport = ResearchReport.model_validate_json(json_text)
            report_json: str = report.model_dump_json(indent=2)

            logger.info("generate_validated_report: validation passed on attempt %d", attempt)
            _cache_report(report_json)
            return report_json

        except ValidationError as exc:
            error_context = f"Pydantic ValidationError:\n{exc}"
            logger.warning(
                "generate_validated_report: validation failed (attempt %d/%d): %s",
                attempt,
                _MAX_VALIDATION_RETRIES,
                exc,
            )
        except json.JSONDecodeError as exc:
            error_context = f"JSON parse error: {exc}"
            logger.warning(
                "generate_validated_report: JSON decode failed (attempt %d/%d): %s",
                attempt,
                _MAX_VALIDATION_RETRIES,
                exc,
            )
        except Exception as exc:  # noqa: BLE001
            error_context = f"Unexpected error: {exc}"
            logger.error(
                "generate_validated_report: unexpected error (attempt %d/%d): %s",
                attempt,
                _MAX_VALIDATION_RETRIES,
                exc,
                exc_info=True,
            )

    # All retries exhausted — return a structured fallback so the pipeline
    # continues rather than crashing with an unhandled exception.
    logger.error(
        "generate_validated_report: all %d attempts failed — returning fallback report",
        _MAX_VALIDATION_RETRIES,
    )
    fallback = ResearchReport(
        title="Synthesis Failed",
        abstract=(
            "The Writer agent was unable to produce a validated report after "
            f"{_MAX_VALIDATION_RETRIES} attempts. Raw data has been cached to "
            f"{_LOGS_DIR} for manual review."
        ),
        comprehensive_analysis=(
            "### Failure Details\n\n"
            "The validation loop exhausted all retry attempts without producing "
            "a schema-conformant JSON response. Review the cached raw data in "
            f"`{_LOGS_DIR}` for the raw research content collected by the Researcher agent."
        ),
        strategic_takeaways=["Report generation failed — see .logs/ for raw research data."],
        primary_sources=list({entry.get("source", entry.get("task", "unknown")) for entry in raw_data}) or ["N/A"],
    )
    fallback_json: str = fallback.model_dump_json(indent=2)
    _cache_report(fallback_json)
    return fallback_json
