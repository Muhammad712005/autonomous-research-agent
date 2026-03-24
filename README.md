# 🕷️ Autonomous Web-Scraping Research Agent

**🔴 Live Demo:** https://autonomous-research-agent-blond.vercel.app/

A full-stack, multi-agent AI system that autonomously researches user-defined goals. It utilizes a LangGraph architecture to break down tasks, scrape live web data using stealth browsers, and synthesize the findings into a comprehensive PDF report.

## 🏗️ Architecture & Tech Stack

### Backend
* **Framework:** FastAPI, Python 3.10
* **AI Orchestration:** LangGraph, LangChain
* **LLM Engine:** Groq API
* **Web Scraping:** Playwright (Stealth), BeautifulSoup4
* **Search APIs:** DuckDuckGo / Yandex
* **Deployment:** Docker, Hugging Face Spaces

### Frontend
* **Framework:** React, Vite
* **Styling:** Tailwind CSS
* **Real-time Communication:** WebSockets
* **Deployment:** Vercel

## ✨ Core Workflow
The system operates using three distinct AI nodes working in a continuous graph:
1.  **Manager Agent:** Evaluates the user's goal and generates a batch of targeted search queries.
2.  **Researcher Agents:** Executes search queries, navigates to URLs via a headless Chromium browser, and scrapes page content while bypassing basic bot protections. Runs asynchronously in parallel.
3.  **Writer Agent:** Synthesizes the raw HTML/text data from the Researchers into a structured Markdown report. Includes built-in retry loops to handle Pydantic validation errors and LLM hallucinations.

## 🚀 Local Setup Instructions

### Prerequisites
* Python 3.10+
* Node.js 18+
* A [Groq API Key](https://console.groq.com/keys)

### 1. Clone the Repository
```bash
git clone [https://github.com/Muhammad712005/autonomous-research-agent.git](https://github.com/Muhammad712005/autonomous-research-agent.git)
cd autonomous-research-agent
```
### 2. Backend Setup
Open a terminal in the root directory:
```bash
# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Set up your environment variable
# Create a .env file in the root directory and add:
GROQ_API_KEY=your_api_key_here

# Run the FastAPI server
python -m uvicorn src.api.server:app --host 0.0.0.0 --port 8000
```
### 3. Frontend Setup
Open a second terminal and navigate to the frontend directory:
```bash
cd frontend

# Install dependencies
npm install

# Set up your environment variable
# Create a .env file in the frontend directory and add:
VITE_WS_URL=ws://localhost:8000/ws/research

# Start the Vite development server
npm run dev
```
👤 Author

Muhammad Alam

    [LinkedIn](www.linkedin.com/in/muhammad-alam-001m17)
