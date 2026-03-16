Master Project Specification: Autonomous Web-Scraping Research Agent
​1. Project Overview & Philosophy
​This project is a backend-heavy, multi-agent autonomous research system. The user inputs a high-level research goal via a strictly keyboard-driven Terminal User Interface (TUI). The system utilizes a multi-agent LLM orchestration layer to break down the goal, navigate the web asynchronously, bypass bot protections, read DOM trees, and compile findings.
​The design philosophy is highly controlled, deterministic, and efficient. The interface must prioritize keyboard navigation over mouse interaction, featuring a dark, sharp, and clean aesthetic with subtle, high-contrast, blood-inspired accents against a deep black terminal background.
​2. Core Architecture (Multi-Agent State Machine)
​The "brain" of the application relies on three distinct AI agents working in a strictly controlled state-machine pipeline to prevent endless loops and hallucinations:
​The Manager Agent: The planner. It receives the user's high-level goal, breaks it down into actionable, sequential search queries and sub-tasks, and routes the state to the Researcher.
​The Researcher Agent: The executioner. Equipped with a custom web-scraping tool and a search API (e.g., Tavily or DuckDuckGo). It navigates headless browsers, evaluates web pages, extracts raw text, and decides if it has gathered enough information to satisfy the Manager's sub-task.
​The Writer Agent: The synthesizer. It ingests the raw, parsed markdown from the Researcher, filters out noise, and formats the final data into a strictly validated JSON structure or a clean PDF report.
​3. Technology Stack
​Language: Python 3.11+ (Strict typing and asynchronous capabilities required).
​Orchestration Framework: LangGraph (Mandatory. Used for deterministic multi-agent routing, node/edge definitions, and state management. Do not use CrewAI).
​Browser/Scraping Engine: Playwright (Async Python API) paired strictly with playwright-stealth plugins to mask the headless Chromium instance and bypass basic bot detection (e.g., Cloudflare Turnstile).
​DOM Parsing: BeautifulSoup4 paired with Markdownify.
​Data Validation/Structuring: Pydantic (to force the Writer Agent to output predictable JSON schemas and handle retry loops for bad outputs).
​User Interface: Textual (Python TUI framework for building the dark, keyboard-driven dashboard).
​Document Generation: WeasyPrint or ReportLab (for converting final JSON/Markdown into professional PDF reports).
​4. UI/UX Design Specifications
​Framework: Textual.
​Aesthetic: Dark mode, sharp edges, clean layout. Minimalist styling utilizing strict CSS hex codes:
​Base Background: #0a0a0a (Deep Black)
​Inactive Panels/Surface: #1a1a1a (Dark Grey)
​Active Borders, Highlights, & Critical Alerts: #8b0000 (Dark Red) or #dc143c (Crimson).
​Layout: A split-screen terminal view.
​Bottom Pane: Command input bar (high-level goal entry).
​Left Pane: Live, real-time streaming log of the agents' thought processes (e.g., [Manager] Delegating task..., [Researcher] Navigating to URL...).
​Right Pane: Structured output view showing the finalized data or compilation progress.
​Interaction: 100% keyboard navigable. No mouse required.
​5. Implementation Roadmap (Task Breakdown)
​The AI must follow this modular breakdown to generate code, ensuring no cross-contamination of logic. Proceed phase-by-phase.
​Phase 1: The Scraper Engine (Asynchronous Extraction & Stealth)
​1.1 Setup: Initialize the async environment and install dependencies.
​1.2 Browser Module: Build Playwright scripts to launch an async headless Chromium instance. CRITICAL: Inject playwright-stealth scripts prior to navigation to prevent fingerprinting. Include network idle waits, timeout, and retry logic.
​1.3 Parsing Utility: Build a function using BeautifulSoup to isolate the <body> or <article> tags. CRITICAL: Aggressively call .decompose() on <header>, <footer>, <aside>, <form>, <nav>, and any elements with classes/IDs containing "ad", "menu", "banner", or "cookie" to sanitize the tree. Then, use Markdownify to return token-efficient Markdown.
​Phase 2: The Agentic Core (LangGraph Orchestration)
​2.1 Tool Creation: Wrap the Phase 1 scraper engine into asynchronous, callable tools.
​2.2 Graph & Agent Definitions: Define the shared State schema. Create the Manager, Researcher, and Writer nodes. Define the conditional edges that route the state between them based on task completion.
​2.3 Pydantic Schemas: Define the exact data structures the Writer agent must adhere to for the final output, and implement an error-correction loop if the LLM output fails validation.
​Phase 3: The TUI Control Room (Textual Integration)
​3.1 Layout Construction: Build the Textual UI with the specified panes (Input, Live Logs, Output) applying the #0a0a0a, #1a1a1a, and #8b0000 color palette.
​3.2 Async Wiring: Connect the LangGraph backend to the Textual frontend. CRITICAL: Ensure all multi-agent orchestration runs within a Textual @work(thread=True) worker decorator, or via asyncio.to_thread. The LLM network calls must absolutely not block the main UI event loop.
​Phase 4: Output Formatting & Hardening
​4.1 PDF Export: Implement the logic to take the Writer Agent's validated JSON and generate a clean, formatted PDF report.
​4.2 Error Handling: Implement robust try/except blocks for CAPTCHA blocks, empty DOM returns, and LLM API timeouts.
​6. Maintenance & Error Handling Requirements
​Rate Limiting: The scraper must include jitter/randomized delays between page navigations to avoid IP bans.
​Token Management: Strictly monitor the length of the Markdown fed back to the LLM context windows. Implement a text-chunking mechanism if a sanitized page is still too long.
​Logging: All raw HTML and agent outputs should be temporarily cached to a local .logs directory for debugging if an agent fails a task mid-run.
