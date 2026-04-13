FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY agent_config.yaml ./
COPY src ./src
COPY scripts ./scripts

RUN pip install --no-cache-dir .

HEALTHCHECK --interval=60s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import sqlite3,os,sys; p=os.environ.get('ANALYSIS_DB_URL','sqlite:////data/analysis.db').replace('sqlite:///',''); sys.exit(0) if os.path.exists(p) and sqlite3.connect(p).execute('SELECT 1') else sys.exit(1)"

ENTRYPOINT ["/app/scripts/hourly_runner.sh"]
