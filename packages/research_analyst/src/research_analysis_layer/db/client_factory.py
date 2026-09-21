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


def resolve_nexus_database_url() -> str | None:
    return (
        env("DATABASE_URL")
        or os.getenv("NEXUS_DATABASE_URL")
        or env("PARSED_DATABASE_URL")
    )


def open_parsed_db_client(settings: Settings) -> ParsedDbClient:
    database_url = settings.parsed_database_url or resolve_nexus_database_url()
    if database_url and database_url.startswith("postgresql"):
        return PostgresParsedDbClient(
            database_url,
            timeout_seconds=settings.request_timeout_seconds,
        )
    return ParsedDbClient(
        base_url=settings.parsed_db_url,
        api_key=settings.parsed_db_key,
        timeout_seconds=settings.request_timeout_seconds,
    )


def open_calendar_db_client(settings: Settings) -> CalendarDbClient:
    database_url = settings.calendar_database_url or resolve_nexus_database_url()
    if database_url and database_url.startswith("postgresql"):
        return PostgresCalendarDbClient(
            database_url,
            timeout_seconds=settings.request_timeout_seconds,
            match_source=settings.calendar_match_source,
            source_name=settings.calendar_source_name,
        )
    return CalendarDbClient(
        base_url=settings.calendar_db_url,
        api_key=settings.calendar_db_key,
        timeout_seconds=settings.request_timeout_seconds,
        match_source=settings.calendar_match_source,
        source_name=settings.calendar_source_name,
    )
