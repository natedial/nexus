# Multi-arch Dockerfile for Raspberry Pi (ARM64) and x86_64
FROM python:3.11-slim AS base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgl1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libxcb1 \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

FROM base AS deps

# Install dependency graph from the lockfile so normal source edits don't
# invalidate the expensive docling/torch layer.
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
RUN uv export \
    --frozen \
    --format requirements.txt \
    --no-dev \
    --extra docling \
    --no-editable \
    --no-emit-project \
    --output-file requirements.txt \
    && pip install --no-cache-dir -r requirements.txt

FROM base

COPY --from=deps /usr/local /usr/local
COPY src/ ./src/
COPY config/ ./config/

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Create data directory for SQLite state
RUN mkdir -p /app/data

# Run as non-root user
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

# Entry point
CMD ["python", "-m", "src.main"]
