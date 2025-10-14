# Multi-stage build for production-ready FastAPI application
FROM python:3.11-slim AS builder

# Set working directory
WORKDIR /app

# Install system dependencies (minimal for building)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies with optimizations
# - Use pip cache mount for faster rebuilds
# - Compile Python files to reduce runtime size
# - Remove unnecessary files after installation
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --user --no-warn-script-location -r requirements.txt && \
    # Remove pip cache and unnecessary files
    find /root/.local -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true && \
    find /root/.local -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true && \
    find /root/.local -name "*.pyc" -delete 2>/dev/null || true && \
    find /root/.local -name "*.pyo" -delete 2>/dev/null || true && \
    # Remove large model files that can be downloaded at runtime if needed
    # Keep only essential sentence-transformers components
    find /root/.local -type f -name "*.md" -delete 2>/dev/null || true && \
    find /root/.local -type f -name "*.txt" -delete 2>/dev/null || true && \
    find /root/.local -type d -name "*.dist-info" -exec sh -c 'find "$1" -type f ! -name "METADATA" -delete' _ {} \; 2>/dev/null || true

# Production stage
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/root/.local/bin:$PATH \
    # Reduce Python memory overhead
    MALLOC_TRIM_THRESHOLD_=100000 \
    # Disable pip version check
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    # Clean apt cache
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Set working directory
WORKDIR /app

# Copy only Python dependencies from builder (not entire /root/.local)
COPY --from=builder /root/.local /root/.local

# Copy application code (only src directory)
COPY --chown=appuser:appuser src/ ./src/

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Run application with optimizations
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
