# Multi-stage build for production-ready FastAPI application
FROM python:3.11-slim AS builder

WORKDIR /app

# Install system dependencies (minimal for building)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install deps for appuser (UID 1000) in /home/appuser/.local
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

USER appuser
ENV PATH=/home/appuser/.local/bin:$PATH

# Install Python deps as appuser
RUN --mount=type=cache,target=/home/appuser/.cache/pip \
    pip install --user --no-warn-script-location -r requirements.txt

# Clean unnecessary files (optional)
RUN find /home/appuser/.local -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true && \
    find /home/appuser/.local -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true && \
    find /home/appuser/.local -name "*.pyc" -delete 2>/dev/null || true


# Production stage
FROM python:3.11-slim

# Create appuser
RUN useradd -m -u 1000 appuser
WORKDIR /app

# Copy installed deps from builder (now in appuser's home)
COPY --from=builder --chown=appuser:appuser /home/appuser/.local /home/appuser/.local

# Copy source code
COPY --chown=appuser:appuser src/ ./src/

USER appuser
ENV PATH=/home/appuser/.local/bin:$PATH

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]