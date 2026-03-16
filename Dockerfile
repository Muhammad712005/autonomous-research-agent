# Uses the official Microsoft Playwright image which pre-installs all
# Chromium system dependencies (libnss3, libgbm, etc.)
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# ── Non-root user (required by Hugging Face Spaces) ──────────────────────────
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR $HOME/app

# ── Dependencies ──────────────────────────────────────────────────────────────
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium browser binary as the non-root user
RUN playwright install chromium

# ── Application source ────────────────────────────────────────────────────────
COPY --chown=user src/ ./src/

# ── Port (Hugging Face Spaces uses 7860) ─────────────────────────────────────
ENV PORT=7860
EXPOSE 7860

CMD ["uvicorn", "src.api.server:app", "--host", "0.0.0.0", "--port", "7860"]
