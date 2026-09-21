"""Construct parsed/calendar clients for the configured backend."""

from __future__ import annotations

import os

from research_analysis_layer.config import Settings
from research_analysis_layer.db.calendar_db_client import CalendarDbClient
from research_analysis_layer.db.parsed_db_client import ParsedDbClient
from research_analysis_layer.db.postgres_parsed_client import (
    PostgresCalendarDbClient,
    PostgresParsedDbClient,
)
from research_analysis_layer.env import env


def resolve_nexus_database_url() -> str:
    url = env("DATABASE_URL") or os.getenv("NEXUS_DATABASE_URL") or env(
        "PARSED_DATABASE_URL"
    )
    if not url:
        raise ValueError(
            "NEXUS_DATABASE_URL is required: set RESEARCH_ANALYST_DATABASE_URL "
            "or NEXUS_DATABASE_URL"
        )
    if not url.startswith("postgresql"):
        raise ValueError(f"database url must be PostgreSQL, received {url!r}")
    return url


def open_parsed_db_client(settings: Settings) -> ParsedDbClient:
    database_url = settings.parsed_database_url or resolve_nexus_database_url()
    return PostgresParsedDbClient(
        database_url,
        timeout_seconds=settings.request_timeout_seconds,
    )


def open_calendar_db_client(settings: Settings) -> CalendarDbClient:
    database_url = settings.calendar_database_url or resolve_nexus_database_url()
    return PostgresCalendarDbClient(
        database_url,
        timeout_seconds=settings.request_timeout_seconds,
        match_source=settings.calendar_match_source,
        source_name=settings.calendar_source_name,
    )
