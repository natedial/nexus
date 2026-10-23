FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY packages/research_pipeline_ops /opt/research_pipeline_ops
COPY packages/research_analyst/pyproject.toml packages/research_analyst/README.md ./
COPY packages/research_analyst/agent_config.yaml ./
COPY packages/research_analyst/prompts ./prompts
COPY packages/research_analyst/src ./src
COPY packages/research_analyst/scripts ./scripts

RUN pip install --no-cache-dir /opt/research_pipeline_ops && pip install --no-cache-dir .

HEALTHCHECK --interval=60s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import sqlite3,os,sys; p=(os.environ.get('RESEARCH_ANALYST_ANALYSIS_DB_URL') or os.environ.get('ANALYSIS_DB_URL','sqlite:////data/analysis.db')).replace('sqlite:///',''); sys.exit(0) if os.path.exists(p) and sqlite3.connect(p).execute('SELECT 1') else sys.exit(1)"

ENTRYPOINT ["/app/scripts/hourly_runner.sh"]
