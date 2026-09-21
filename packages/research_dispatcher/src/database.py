"""PostgreSQL calendar queries for dispatcher reports."""

from __future__ import annotations

from datetime import date, timedelta

import psycopg
from psycopg.rows import dict_row

from config import Config


class DatabaseClient:
    """Read economic and supply calendar events from local PostgreSQL."""

    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or Config.DATABASE_URL
        if not self.database_url:
            raise ValueError(
                "DATABASE_URL is required: set RESEARCH_DISPATCHER_DATABASE_URL "
                "or NEXUS_DATABASE_URL"
            )

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def _get_upcoming_week_range(self) -> tuple[date, date]:
        """Monday-Friday for the current or next week depending on weekday."""
        today = date.today()
        weekday = today.weekday()

        if weekday <= 4:
            monday = today - timedelta(days=weekday)
        else:
            days_until_monday = 7 - weekday
            monday = today + timedelta(days=days_until_monday)

        friday = monday + timedelta(days=4)
        return monday, friday

    def query_economic_events(self) -> list[dict]:
        """Query economic events for the upcoming Monday-Friday window."""
        monday, friday = self._get_upcoming_week_range()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT event_date, time_ny, event_name, consensus, importance_indicator
                FROM economic_events
                WHERE country = %s
                  AND event_date >= %s
                  AND event_date <= %s
                ORDER BY event_date, time_ny
                """,
                (Config.CALENDAR_COUNTRY, monday.isoformat(), friday.isoformat()),
            ).fetchall()
        return [dict(row) for row in rows]

    def query_supply_events(self) -> list[dict]:
        """Query supply events for the upcoming Monday-Friday window."""
        monday, friday = self._get_upcoming_week_range()
        with self._connect() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT event_date, time_ny, description, size_bn, maturity
                    FROM supply_events
                    WHERE country = %s
                      AND event_date >= %s
                      AND event_date <= %s
                    ORDER BY event_date, time_ny
                    """,
                    (Config.CALENDAR_COUNTRY, monday.isoformat(), friday.isoformat()),
                ).fetchall()
            except psycopg.errors.UndefinedTable:
                return []
        return [dict(row) for row in rows]
