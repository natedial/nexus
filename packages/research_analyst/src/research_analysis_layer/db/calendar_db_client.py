"""Calendar matching client for forecast uploads."""

from __future__ import annotations

from research_analysis_layer.db.parsed_db_client import ParsedDbClient


class CalendarDbClient(ParsedDbClient):
    """Supabase/PostgREST client for calendar matching tables."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout_seconds: int = 30,
        match_source: str = "economic_events",
        source_name: str = "economic_events",
    ):
        super().__init__(base_url, api_key, timeout_seconds=timeout_seconds)
        self.match_source = match_source
        self.source_name = source_name

    def check_connection(self) -> tuple[bool, str]:
        """Run a lightweight connectivity check against the configured calendar source."""
        table = "release_dates" if self.match_source == "release_dates" else "economic_events"
        try:
            self._get(table, {"select": "id", "limit": "1"})
        except Exception as exc:  # pragma: no cover - exercised by CLI
            return False, str(exc)
        return True, "ok"

    def search_calendar_matches(
        self,
        *,
        release_date: str | None = None,
        country: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Return normalized rows suitable for forecast matcher scoring."""
        if self.match_source == "release_dates":
            return self._search_release_dates(
                release_date=release_date,
                country=country,
                limit=limit,
            )
        return self.search_economic_events(
            release_date=release_date,
            country=country,
            limit=limit,
        )

    def _search_release_dates(
        self,
        *,
        release_date: str | None = None,
        country: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        params: list[tuple[str, str]] = [
            ("select", "id,release_id,release_date"),
            ("order", "release_date.asc,release_id.asc"),
            ("limit", str(limit)),
        ]
        if release_date:
            params.append(("release_date", f"eq.{release_date}"))
        date_rows = self._get("release_dates", params)
        if not date_rows:
            return []

        release_ids = sorted(
            {
                int(row["release_id"])
                for row in date_rows
                if row.get("release_id") is not None
            }
        )
        if not release_ids:
            return []

        joined = ",".join(str(item) for item in release_ids)
        release_rows = self._get(
            "releases",
            {
                "select": "id,name,fred_release_id,link,press_release",
                "id": f"in.({joined})",
            },
        )
        releases_by_id = {
            int(row["id"]): row
            for row in release_rows
            if row.get("id") is not None
        }

        normalized_rows: list[dict] = []
        for row in date_rows:
            release_id = row.get("release_id")
            if release_id is None:
                continue
            release = releases_by_id.get(int(release_id))
            release_name = (
                str(release.get("name"))
                if release and release.get("name") is not None
                else f"Release {release_id}"
            )
            normalized_rows.append(
                {
                    "id": str(row.get("id") or ""),
                    "calendar_release_id": str(row.get("id") or ""),
                    "calendar_source": self.source_name,
                    "event_name": release_name,
                    "event_date": row.get("release_date"),
                    "country": country or "US",
                    "period": None,
                    "time_ny": None,
                    "fred_release_id": (
                        release.get("fred_release_id")
                        if release is not None
                        else None
                    ),
                }
            )
        return normalized_rows
