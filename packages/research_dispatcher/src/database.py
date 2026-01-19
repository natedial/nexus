from supabase import create_client, Client
from config import Config
from datetime import datetime, timedelta, date


class DatabaseClient:
    """Handles connection and queries to Supabase PostgreSQL database."""

    def __init__(self):
        self.client: Client = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)

    def query_analysis(self):
        """
        Query parsed_research documents based on configured filters.

        Returns documents with full parsed_data JSONB:
        - themes, trades, through_lines from parsed_data
        - publisher from parsed_data->metadata
        - synthesis status and metadata

        Filters applied:
        - Date range: Config.DATE_RANGE_DAYS
        - Sources: Config.FILTER_SOURCES (comma-separated, empty = all)
        - Region: Config.FILTER_REGION (from parsed_data->metadata->region)
        - Asset focus: Config.FILTER_ASSET_FOCUS (from parsed_data->metadata->asset_focus)
        """
        # Calculate date range based on config
        date_threshold = (datetime.now() - timedelta(days=Config.DATE_RANGE_DAYS)).strftime('%Y-%m-%d')

        # Build query
        query = (
            self.client.table('parsed_research')
            .select('*')
            .gte('parsed_at', date_threshold)
        )

        # Apply source filter if configured
        if Config.FILTER_SOURCES:
            sources = [s.strip() for s in Config.FILTER_SOURCES.split(',')]
            query = query.in_('source', sources)

        # Apply region filter if configured (filters on JSONB metadata)
        if Config.FILTER_REGION:
            query = query.eq('parsed_data->metadata->>region', Config.FILTER_REGION)

        # Apply asset focus filter if configured (filters on JSONB metadata)
        if Config.FILTER_ASSET_FOCUS:
            query = query.eq('parsed_data->metadata->>asset_focus', Config.FILTER_ASSET_FOCUS)

        # Execute query
        response = query.order('parsed_at', desc=True).execute()

        return response.data

    def mark_as_synthesized(self, document_ids: list) -> bool:
        """
        Mark documents as synthesized after successful report generation.

        Args:
            document_ids: List of document IDs to mark as synthesized

        Returns:
            True if successful, False otherwise
        """
        if not document_ids:
            return True

        try:
            response = (
                self.client.table('parsed_research')
                .update({'synthesized': True})
                .in_('id', document_ids)
                .execute()
            )
            return True
        except Exception as e:
            print(f"Error marking documents as synthesized: {e}")
            return False

    def _get_upcoming_week_range(self):
        """Get the Monday-Friday date range for the upcoming week."""
        today = date.today()
        # Find next Monday
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7  # If today is Monday, get next Monday

        next_monday = today + timedelta(days=days_until_monday)
        next_friday = next_monday + timedelta(days=4)

        return next_monday, next_friday

    def query_economic_events(self):
        """
        Query economic events for the upcoming week (Monday-Friday).

        Returns events with: event_date, time_ny, event_name, consensus

        Filters applied:
        - Country: Config.CALENDAR_COUNTRY
        """
        monday, friday = self._get_upcoming_week_range()

        response = (
            self.client.table('economic_events')
            .select('event_date, time_ny, event_name, consensus, importance_indicator')
            .eq('country', Config.CALENDAR_COUNTRY)
            .gte('event_date', monday.isoformat())
            .lte('event_date', friday.isoformat())
            .order('event_date')
            .order('time_ny')
            .execute()
        )

        return response.data

    def query_supply_events(self):
        """
        Query supply events for the upcoming week (Monday-Friday).

        Returns events with: event_date, time_ny, description, size_bn

        Filters applied:
        - Country: Config.CALENDAR_COUNTRY
        """
        monday, friday = self._get_upcoming_week_range()

        response = (
            self.client.table('supply_events')
            .select('event_date, time_ny, description, size_bn, maturity')
            .eq('country', Config.CALENDAR_COUNTRY)
            .gte('event_date', monday.isoformat())
            .lte('event_date', friday.isoformat())
            .order('event_date')
            .order('time_ny')
            .execute()
        )

        return response.data

    def query_all_recent(self):
        """
        Alternative query: Get all fields including full parsed_data JSONB.
        Useful if you need access to the complete JSONB structure.
        """
        seven_days_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

        response = (
            self.client.table('parsed_research')
            .select('*')
            .gte('parsed_at', seven_days_ago)
            .order('parsed_at', desc=True)
            .execute()
        )

        return response.data
