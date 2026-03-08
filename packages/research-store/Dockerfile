FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml setup.cfg setup.py README.md /app/
COPY distill_tool /app/distill_tool

RUN pip install --upgrade pip \
    && pip install -e . pytest

CMD ["bash"]
