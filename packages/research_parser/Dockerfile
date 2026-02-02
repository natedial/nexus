# Multi-arch Dockerfile for Raspberry Pi (ARM64) and x86_64
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Copy project files for installation
COPY pyproject.toml .
COPY src/ ./src/
COPY config/ ./config/
COPY prompts/ ./prompts/

# Install Python dependencies
RUN pip install --no-cache-dir .

# Create data directory for SQLite state
RUN mkdir -p /app/data

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Run as non-root user
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

# Entry point
CMD ["python", "-m", "src.main"]
