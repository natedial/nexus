from supabase import create_client, Client
from config import Config
from datetime import datetime, timedelta


class DatabaseClient:
    """Handles connection and queries to Supabase PostgreSQL database."""

    def __init__(self):
        self.client: Client = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)

    def query_analysis(self):
        """
        Query parsed_research documents from the last 7 days.

        Returns documents with full parsed_data JSONB:
        - themes, trades, through_lines from parsed_data
        - publisher from parsed_data->metadata
        - synthesis status and metadata
        """
        # Calculate date 7 days ago
        seven_days_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

        # Query all fields - formatter will extract JSONB fields as needed
        response = (
            self.client.table('parsed_research')
            .select('*')
            .gte('source_date', seven_days_ago)
            .order('source_date', desc=True)
            .execute()
        )

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

    def query_all_recent(self):
        """
        Alternative query: Get all fields including full parsed_data JSONB.
        Useful if you need access to the complete JSONB structure.
        """
        seven_days_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

        response = (
            self.client.table('parsed_research')
            .select('*')
            .gte('source_date', seven_days_ago)
            .order('source_date', desc=True)
            .execute()
        )

        return response.data
