from typing import List, Dict, Any
from datetime import datetime, timedelta
from collections import defaultdict
import hashlib


class ReportFormatter:
    """Formats query results into structured report data for parsed_research."""

    def format_report(self, data: List[Dict[str, Any]], active_filters: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Format raw database results into a structured report.

        Args:
            data: List of records from database query
            active_filters: Optional dict of active filters for display in report

        Returns:
            Dictionary containing formatted report sections
        """
        return {
            'title': 'Research Dispatch',
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'active_filters': active_filters or {},
            'summary': self._create_summary(data),
            'details': self._format_details(data),
            'themes_analysis': self._aggregate_themes(data),
            'trades': self._aggregate_trades(data),
            'through_lines': self._aggregate_through_lines(data),
            'callouts': self._aggregate_callouts(data)
        }

    def _create_summary(self, data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create summary statistics from the parsed_research data."""
        total_documents = len(data)

        # Date range
        seven_days_ago = datetime.now() - timedelta(days=7)
        date_range = f"{seven_days_ago.strftime('%Y-%m-%d')} to {datetime.now().strftime('%Y-%m-%d')}"

        summary = {
            'total_documents': total_documents,
            'date_range': date_range
        }

        # Synthesis status breakdown
        synthesis_status = {'synthesized': 0, 'pending': 0}
        sources = {}
        publishers = {}

        for record in data:
            # Count synthesis status
            if record.get('synthesized'):
                synthesis_status['synthesized'] += 1
            else:
                synthesis_status['pending'] += 1

            # Count by source
            source = record.get('source', 'Unknown')
            sources[source] = sources.get(source, 0) + 1

            # Count by publisher (from JSONB metadata)
            parsed_data = record.get('parsed_data', {})
            if parsed_data:
                metadata = parsed_data.get('metadata', {})
                publisher = metadata.get('publisher', 'Unknown')
                if publisher and publisher != 'Unknown':
                    publishers[publisher] = publishers.get(publisher, 0) + 1

        summary['synthesis_status'] = synthesis_status
        summary['by_source'] = sources
        if publishers:
            summary['by_publisher'] = publishers

        return summary

    def _format_details(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Format individual records for detailed section."""
        formatted = []

        for record in data:
            parsed_data = record.get('parsed_data', {})
            metadata = parsed_data.get('metadata', {}) if parsed_data else {}
            themes = parsed_data.get('themes', []) if parsed_data else []
            trades = parsed_data.get('trades', []) if parsed_data else []

            formatted_record = {
                'id': record.get('id'),
                'document_name': record.get('document_name', 'Untitled'),
                'source': record.get('source', 'Unknown'),
                'source_date': record.get('source_date', ''),
                'publisher': metadata.get('publisher', 'N/A'),
                'synthesized': 'Yes' if record.get('synthesized') else 'No',
                'themes_count': len(themes) if isinstance(themes, list) else 0,
                'trades_count': len(trades) if isinstance(trades, list) else 0
            }
            formatted.append(formatted_record)

        return formatted

    def _aggregate_themes(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Aggregate and format themes across all documents.
        Returns top themes with their occurrences.
        Only shows document name first time it appears across all themes.
        """
        theme_counts = {}
        theme_examples = {}
        seen_documents = set()  # Track which documents we've already shown

        for record in data:
            parsed_data = record.get('parsed_data', {})
            themes = parsed_data.get('themes', []) if parsed_data else []
            if not themes or not isinstance(themes, list):
                continue

            doc_name = record.get('document_name', 'Unknown Document')

            for theme in themes:
                if not isinstance(theme, dict):
                    continue

                label = theme.get('label', 'Unlabeled')

                # Count occurrences
                if label not in theme_counts:
                    theme_counts[label] = 0
                    theme_examples[label] = []

                theme_counts[label] += 1

                # Store example context (limit to first 3 examples)
                if len(theme_examples[label]) < 3:
                    theme_examples[label].append({
                        'document': doc_name,
                        'context': theme.get('context', ''),  # Full context, no truncation
                        'show_document': doc_name not in seen_documents  # Only show if not seen before
                    })
                    seen_documents.add(doc_name)

        # Sort by frequency and format
        sorted_themes = sorted(theme_counts.items(), key=lambda x: x[1], reverse=True)

        formatted_themes = []
        for label, count in sorted_themes[:10]:  # Top 10 themes
            formatted_themes.append({
                'label': label,
                'count': count,
                'examples': theme_examples[label]
            })

        return formatted_themes

    def _aggregate_trades(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Aggregate and format trades across all documents.
        Returns all trades with their metadata.
        """
        all_trades = []

        for record in data:
            parsed_data = record.get('parsed_data', {})
            trades = parsed_data.get('trades', []) if parsed_data else []
            if not trades or not isinstance(trades, list):
                continue

            doc_name = record.get('document_name', 'Unknown Document')
            source = record.get('source', 'Unknown Source')
            source_date = record.get('source_date', '')

            for trade in trades:
                if not isinstance(trade, dict):
                    continue

                all_trades.append({
                    'text': trade.get('text', 'N/A'),
                    'exposure': trade.get('exposure', 'N/A'),
                    'rationale': trade.get('rationale', ''),
                    'timeframe': trade.get('timeframe', 'N/A'),
                    'conviction': trade.get('conviction', 'N/A'),
                    'trigger_levels': trade.get('trigger_levels'),
                    'document': doc_name,
                    'source': source,
                    'date': source_date
                })

        return all_trades

    def _aggregate_through_lines(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Aggregate and format through_lines across all documents.
        Returns all through_lines with their metadata.
        """
        all_through_lines = []

        for record in data:
            parsed_data = record.get('parsed_data', {})
            through_lines = parsed_data.get('through_lines', []) if parsed_data else []
            if not through_lines or not isinstance(through_lines, list):
                continue

            doc_name = record.get('document_name', 'Unknown Document')
            source = record.get('source', 'Unknown Source')

            for tl in through_lines:
                if not isinstance(tl, dict):
                    continue

                lead = tl.get('lead', '')
                all_through_lines.append({
                    'lead': lead,
                    'key_insight': tl.get('key_insight', ''),
                    'supporting_themes': tl.get('supporting_themes', []),
                    'supporting_trades': tl.get('supporting_trades', []),
                    'document': doc_name,
                    'source': source,
                    'item_id': hashlib.md5(lead.encode()).hexdigest()[:8],
                    'record_id': record.get('id')
                })

        return all_through_lines

    def _aggregate_callouts(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Aggregate callouts across all documents.
        Returns all callouts with source attribution.
        Handles missing or empty callouts gracefully.
        """
        all_callouts = []

        for record in data:
            parsed_data = record.get('parsed_data', {})
            if not parsed_data:
                continue

            callouts = parsed_data.get('callouts', [])
            if not callouts or not isinstance(callouts, list):
                continue

            source = record.get('source', 'Unknown Source')
            doc_name = record.get('document_name', 'Unknown Document')

            for callout in callouts:
                if not isinstance(callout, dict):
                    continue

                text = callout.get('text', '').strip()
                if not text:
                    continue

                all_callouts.append({
                    'text': text,
                    'source_through_line': callout.get('source_through_line', ''),
                    'source': source,
                    'document': doc_name
                })

        return all_callouts

    def format_economic_calendar(self, events: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Format economic events grouped by day of week.

        Returns dict with day names as keys and list of events as values.
        """
        grouped = defaultdict(list)

        for event in events:
            event_date = event.get('event_date')
            if not event_date:
                continue

            # Parse date and get day of week
            date_obj = datetime.fromisoformat(event_date).date()
            day_name = date_obj.strftime('%A')  # e.g., "Monday"

            grouped[day_name].append({
                'time': event.get('time_ny', 'N/A'),
                'event': event.get('event_name', 'N/A'),
                'consensus': event.get('consensus', '—')
            })

        # Sort by weekday order
        weekday_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
        sorted_grouped = {day: grouped[day] for day in weekday_order if day in grouped}

        return sorted_grouped

    def format_supply_calendar(self, events: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Format supply events grouped by day of week.

        Returns dict with day names as keys and list of events as values.
        """
        grouped = defaultdict(list)

        for event in events:
            event_date = event.get('event_date')
            if not event_date:
                continue

            # Parse date and get day of week
            date_obj = datetime.fromisoformat(event_date).date()
            day_name = date_obj.strftime('%A')  # e.g., "Monday"

            grouped[day_name].append({
                'time': event.get('time_ny', 'N/A'),
                'description': event.get('description', 'N/A'),
                'size': event.get('size_bn', '—')
            })

        # Sort by weekday order
        weekday_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
        sorted_grouped = {day: grouped[day] for day in weekday_order if day in grouped}

        return sorted_grouped
