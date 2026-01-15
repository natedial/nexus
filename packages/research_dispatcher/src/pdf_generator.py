from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.platypus.flowables import HRFlowable
from reportlab.lib import colors
from typing import Dict, Any
from urllib.parse import urlencode
import base64
import hashlib
import hmac
import json
import time
import os
import yaml
from datetime import datetime

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config


class PDFGenerator:
    """Generates PDF reports from formatted data."""

    def __init__(self, output_dir: str = '.', format_rules_path: str = 'format_rules.yaml'):
        self.output_dir = output_dir
        self.format_rules = self._load_format_rules(format_rules_path)
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _load_format_rules(self, path: str) -> Dict[str, Any]:
        """Load formatting rules from YAML file."""
        try:
            # Try the provided path first
            with open(path, 'r') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            # Try relative to the script's directory
            try:
                script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                full_path = os.path.join(script_dir, path)
                with open(full_path, 'r') as f:
                    return yaml.safe_load(f)
            except FileNotFoundError:
                print(f"Warning: {path} not found, using default colors")
                return {}

    def _setup_custom_styles(self):
        """Create custom paragraph styles dynamically from format_rules.yaml."""
        # Get colors from YAML or use defaults
        title_config = self.format_rules.get('TITLE', [{}])[0]
        title_bg_config = self.format_rules.get('TITLE_BACKGROUND', [{}])[0]

        h1_config = self.format_rules.get('H1_HEADING', [{}])[0]
        h1_bg_config = self.format_rules.get('H1_BACKGROUND', [{}])[0]

        h2_config = self.format_rules.get('H2_HEADING', [{}])[0]
        h2_bg_config = self.format_rules.get('H2_BACKGROUND', [{}])[0]

        minimalist_config = self.format_rules.get('MINIMALIST_TEXT', [{}])[0]

        # Title style - bold, large, black on white
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=title_config.get('font_size', 48),
            textColor=colors.HexColor(title_config.get('font_color', '#000000')),
            spaceAfter=title_config.get('space_after', 40),
            spaceBefore=title_config.get('space_before', 20),
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        ))

        # H1 Section Header - clean, bold, black text
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self.styles['Heading2'],
            fontSize=h1_config.get('font_size', 28),
            textColor=colors.HexColor(h1_config.get('font_color', '#000000')),
            spaceAfter=h1_config.get('space_after', 20),
            spaceBefore=h1_config.get('space_before', 30),
            fontName='Helvetica-Bold'
        ))

        # H2 Subsection Header
        self.styles.add(ParagraphStyle(
            name='SubsectionHeader',
            parent=self.styles['Heading2'],
            fontSize=h2_config.get('font_size', 20),
            textColor=colors.HexColor(h2_config.get('font_color', '#000000')),
            spaceAfter=h2_config.get('space_after', 16),
            spaceBefore=h2_config.get('space_before', 16),
            fontName='Helvetica-Bold'
        ))

        # Accent style for small labels (coral red)
        accent_config = self.format_rules.get('ACCENT_TEXT', [{}])[0]
        self.styles.add(ParagraphStyle(
            name='Accent',
            parent=self.styles['Normal'],
            fontSize=accent_config.get('font_size', 9),
            textColor=colors.HexColor(accent_config.get('font_color', '#FF4458')),
            spaceAfter=accent_config.get('space_after', 6),
            spaceBefore=accent_config.get('space_before', 0),
            fontName='Helvetica-Bold'
        ))

        # Minimalist style for timestamps and metadata
        self.styles.add(ParagraphStyle(
            name='Minimalist',
            parent=self.styles['Normal'],
            fontSize=minimalist_config.get('font_size', 8),
            textColor=colors.HexColor(minimalist_config.get('font_color', '#999999')),
            spaceAfter=minimalist_config.get('space_after', 6),
            spaceBefore=minimalist_config.get('space_before', 0)
        ))

        # Callout quote style - italic, slightly larger
        self.styles.add(ParagraphStyle(
            name='CalloutQuote',
            parent=self.styles['Normal'],
            fontSize=12,
            textColor=colors.HexColor('#333333'),
            fontName='Helvetica-Oblique',
            leading=16,
            spaceAfter=4
        ))

        # Callout attribution style
        self.styles.add(ParagraphStyle(
            name='CalloutAttribution',
            parent=self.styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#666666'),
            fontName='Helvetica',
            alignment=2  # Right align
        ))

        # Feedback links style
        self.styles.add(ParagraphStyle(
            name='FeedbackLinks',
            parent=self.styles['Normal'],
            fontSize=8,
            textColor=colors.HexColor('#666666'),
            spaceAfter=8,
            spaceBefore=2
        ))

    def _format_date_range(self, start: str, end: str) -> str:
        """Format YYYY-MM-DD date range into '22Dec to 29Dec'."""
        try:
            start_dt = datetime.fromisoformat(start)
            end_dt = datetime.fromisoformat(end)
        except ValueError:
            return f"{start} to {end}"

        def _fmt(dt: datetime) -> str:
            month = dt.strftime("%b")
            return f"{dt.day}{month}"

        if start_dt.date() == end_dt.date():
            return _fmt(start_dt)
        return f"{_fmt(start_dt)} to {_fmt(end_dt)}"

    def _create_feedback_links(self, doc_id: str, item_id: str) -> str:
        """
        Create feedback links HTML for a theme or through-line.

        Args:
            doc_id: Document ID from parsed_research
            item_id: Unique item identifier (hash)

        Returns:
            HTML string with clickable links: [Useful] [Flag] [Full Text]
        """
        feedback_url = Config.FEEDBACK_BASE_URL
        if not feedback_url or not doc_id:
            return ""

        # Static document viewer page (fetches JSON from Edge Function)
        viewer_url = Config.DOCUMENT_VIEWER_URL
        token = self._sign_document_link(doc_id)

        useful_url = f"{feedback_url}?{urlencode({'doc': doc_id, 'item': item_id, 'action': 'useful'})}"
        flag_url = f"{feedback_url}?{urlencode({'doc': doc_id, 'item': item_id, 'action': 'flag'})}"
        view_params = {'id': doc_id}
        if token:
            view_params['token'] = token
        view_url = f"{viewer_url}?{urlencode(view_params)}"

        return (
            f'&nbsp;&nbsp;&nbsp;&nbsp;'
            f'[<a href="{useful_url}" color="#0066cc">Useful</a>] '
            f'[<a href="{flag_url}" color="#0066cc">Flag</a>] '
            f'[<a href="{view_url}" color="#0066cc">Full Text</a>]'
        )

    def _sign_document_link(self, doc_id: str) -> str | None:
        """Create a short-lived signed token for document viewing."""
        secret = Config.DOCUMENT_LINK_SECRET
        if not secret or not doc_id:
            return None

        expires_at = int(time.time()) + (Config.DOCUMENT_LINK_TTL_DAYS * 86400)
        payload = {"id": doc_id, "exp": expires_at}
        payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")

        signature = hmac.new(
            secret.encode("utf-8"),
            payload_b64.encode("ascii"),
            hashlib.sha256,
        ).digest()
        signature_b64 = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
        return f"{payload_b64}.{signature_b64}"

    def _create_callout_box(self, callout: Dict[str, Any]) -> list:
        """
        Create a styled callout box with coral red left border.

        Args:
            callout: Dictionary with 'text' and 'source' keys

        Returns:
            List of flowables for the callout box
        """
        elements = []

        # Build the quote with quotation marks
        quote_text = f'"{callout["text"]}"'
        quote_para = Paragraph(quote_text, self.styles['CalloutQuote'])

        # Attribution line
        source_label = callout.get("source", "Multiple")
        if "," in source_label or source_label == "Multiple":
            attribution = f"— Sources: {source_label}"
        else:
            attribution = f"— {source_label}"
        attr_para = Paragraph(attribution, self.styles['CalloutAttribution'])

        # Create a table with the coral red left border effect
        # Using nested table: outer for border, inner for content
        content_table = Table(
            [[quote_para], [attr_para]],
            colWidths=[5.5 * inch]
        )
        content_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))

        # Outer table with coral red left border
        border_cell = Table([['']], colWidths=[4], rowHeights=[None])
        border_cell.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#FF4458')),
        ]))

        # Combine border and content
        callout_table = Table(
            [[border_cell, content_table]],
            colWidths=[4, 5.5 * inch]
        )
        callout_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BACKGROUND', (1, 0), (1, 0), colors.HexColor('#F8F8F8')),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))

        elements.append(Spacer(1, 0.2 * inch))
        elements.append(callout_table)
        elements.append(Spacer(1, 0.2 * inch))

        return elements

    def generate(self, report_data: Dict[str, Any], filename: str = 'report.pdf') -> str:
        """
        Generate PDF from report data.

        Args:
            report_data: Formatted report data dictionary
            filename: Output filename

        Returns:
            Full path to generated PDF file
        """
        filepath = os.path.join(self.output_dir, filename)
        doc = SimpleDocTemplate(filepath, pagesize=letter)
        story = []

        # Get callouts and index by source_through_line for positioning
        callouts = report_data.get('callouts', [])
        callouts_by_through_line = {}
        for callout in callouts:
            source_tl = callout.get('source_through_line', '')
            if source_tl:
                callouts_by_through_line[source_tl] = callout

        def get_callout_for_through_line(lead):
            """Get callout elements if one exists for this through-line."""
            if lead in callouts_by_through_line:
                return self._create_callout_box(callouts_by_through_line[lead])
            return []

        # Title
        title = Paragraph(report_data['title'], self.styles['CustomTitle'])
        story.append(title)

        # Accent label (coral red)
        subtitle = "Weekly Synthesis - "
        source_date_range = report_data.get("source_date_range")
        if source_date_range:
            start = source_date_range.get("start")
            end = source_date_range.get("end")
            if start and end:
                subtitle = f"{subtitle} {self._format_date_range(start, end)}"
        accent_label = Paragraph(subtitle, self.styles['Accent'])
        story.append(accent_label)

        # Generation timestamp
        timestamp = Paragraph(f"Generated: {report_data['generated_at']}", self.styles['Minimalist'])
        story.append(timestamp)

        # Active filters banner (if any filters are set)
        active_filters = report_data.get('active_filters', {})
        if active_filters:
            filter_parts = []
            if active_filters.get('region'):
                filter_parts.append(f"Region: {active_filters['region']}")
            if active_filters.get('asset_focus'):
                filter_parts.append(f"Asset: {active_filters['asset_focus']}")
            if active_filters.get('sources'):
                filter_parts.append(f"Sources: {active_filters['sources']}")
            if active_filters.get('date_range_days'):
                filter_parts.append(f"Date Range: {active_filters['date_range_days']} days")
            if filter_parts:
                filter_text = " | ".join(filter_parts)
                story.append(Paragraph(f"Filters: {filter_text}", self.styles['Minimalist']))

        story.append(Spacer(1, 0.5 * inch))

        # Through Lines section
        through_lines = report_data.get('through_lines', [])
        if through_lines:
            story.append(Paragraph('Through Lines', self.styles['SectionHeader']))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#FF4458'), spaceBefore=3, spaceAfter=12))

            for tl in through_lines:
                # Lead
                if tl.get('lead'):
                    lead_text = f"<b>{tl['lead']}</b>"
                    story.append(Paragraph(lead_text, self.styles['Normal']))

                # Key insight
                if tl.get('key_insight'):
                    story.append(Paragraph(f"&nbsp;&nbsp;&nbsp;&nbsp;{tl['key_insight']}", self.styles['Normal']))

                # Inline tags: Themes | Trades | Sources
                tags = []
                if tl.get('supporting_themes'):
                    themes_list = ', '.join(tl['supporting_themes'])
                    tags.append(f"Themes: {themes_list}")
                if tl.get('supporting_trades'):
                    trades_list = ', '.join(tl['supporting_trades'])
                    tags.append(f"Trades: {trades_list}")

                source = tl.get("source")
                document = tl.get("document")
                supporting_sources = tl.get("supporting_sources")
                if source:
                    label = "Sources" if "," in source or source == "Multiple" else "Source"
                    tags.append(f"{label}: {source}")
                elif supporting_sources:
                    sources_text = ", ".join(supporting_sources)
                    tags.append(f"Sources: {sources_text}")

                if document:
                    doc_text = document[:80] + ("..." if len(document) > 80 else "")
                    tags.append(f"Doc: {doc_text}")

                if tags:
                    tag_line = " | ".join(tags)
                    story.append(
                        Paragraph(
                            f"&nbsp;&nbsp;&nbsp;&nbsp;<i>{tag_line}</i>",
                            self.styles['Normal'],
                        )
                    )

                # Add feedback links for through-lines
                doc_id = tl.get('doc_id', '')
                item_id = tl.get('item_id', '')
                if doc_id and item_id:
                    feedback_links = self._create_feedback_links(doc_id, item_id)
                    if feedback_links:
                        story.append(Paragraph(feedback_links, self.styles['FeedbackLinks']))

                story.append(Spacer(1, 0.15 * inch))

                # Insert callout if one is associated with this through-line
                if tl.get('lead'):
                    story.extend(get_callout_for_through_line(tl['lead']))

            story.append(Spacer(1, 0.2 * inch))

        # Themes Analysis section (moved to top)
        themes_analysis = report_data.get('themes_analysis', [])
        if themes_analysis:
            story.append(Paragraph('Thematic Analysis', self.styles['SectionHeader']))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#FF4458'), spaceBefore=3, spaceAfter=12))

            for theme in themes_analysis:
                # Theme label (with count only if >= 2)
                count = theme['count']
                if count >= 2:
                    theme_title = f"<b>{theme['label']}</b> ({count} occurrences)"
                else:
                    theme_title = f"<b>{theme['label']}</b>"
                story.append(Paragraph(theme_title, self.styles['Normal']))

                # Example contexts (show document name only first time)
                examples = theme.get('examples', [])
                for example in examples:
                    context = example.get('context', '')
                    if context:
                        # Only show document name if this is the first time we've seen it
                        if example.get('show_document', True):
                            doc_name = example.get('document', 'Unknown')
                            story.append(Paragraph(
                                f"&nbsp;&nbsp;&nbsp;&nbsp;<i>({doc_name}):</i> {context}",
                                self.styles['Normal']
                            ))
                        else:
                            # Just show context without document name
                            story.append(Paragraph(
                                f"&nbsp;&nbsp;&nbsp;&nbsp;{context}",
                                self.styles['Normal']
                            ))

                        # Add feedback links
                        doc_id = example.get('doc_id', '')
                        item_id = example.get('item_id', '')
                        if doc_id and item_id:
                            feedback_links = self._create_feedback_links(doc_id, item_id)
                            if feedback_links:
                                story.append(Paragraph(feedback_links, self.styles['FeedbackLinks']))

                story.append(Spacer(1, 0.15 * inch))

            story.append(Spacer(1, 0.2 * inch))


        # Trades section
        trades = report_data.get('trades', [])
        if trades:
            story.append(Paragraph('Trade Recommendations', self.styles['SectionHeader']))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#FF4458'), spaceBefore=3, spaceAfter=12))

            for trade in trades:
                # Trade text and metadata
                trade_header = f"<b>{trade['text']}</b>"
                story.append(Paragraph(trade_header, self.styles['Normal']))

                # Trade details (exposure, timeframe, conviction)
                details_line = f"&nbsp;&nbsp;&nbsp;&nbsp;<i>Exposure: {trade['exposure']} | Timeframe: {trade['timeframe']} | Conviction: {trade['conviction']}</i>"
                story.append(Paragraph(details_line, self.styles['Normal']))

                # Rationale
                if trade.get('rationale'):
                    story.append(Paragraph(f"&nbsp;&nbsp;&nbsp;&nbsp;{trade['rationale']}", self.styles['Normal']))

                # Trigger levels
                if trade.get('trigger_levels'):
                    story.append(Paragraph(f"&nbsp;&nbsp;&nbsp;&nbsp;<i>Triggers: {trade['trigger_levels']}</i>", self.styles['Normal']))

                # Source document
                source_info = f"&nbsp;&nbsp;&nbsp;&nbsp;<i>Source: {trade['source']} - {trade['document'][:80]}{'...' if len(trade['document']) > 80 else ''} ({trade['date']})</i>"
                story.append(Paragraph(source_info, self.styles['Normal']))

                story.append(Spacer(1, 0.15 * inch))

            story.append(Spacer(1, 0.2 * inch))


        # Economic Calendar section
        economic_calendar = report_data.get('economic_calendar', {})
        if economic_calendar:
            story.append(Paragraph('Economic Calendar', self.styles['SectionHeader']))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#FF4458'), spaceBefore=3, spaceAfter=12))

            for day, events in economic_calendar.items():
                # Day header
                day_header = Paragraph(f"<b>{day}</b>", self.styles['Normal'])
                story.append(day_header)

                # Create table for this day
                table_data = [['Time NY', 'Event', 'Consensus']]  # Headers
                for event in events:
                    table_data.append([
                        event['time'],
                        event['event'],
                        event['consensus']
                    ])

                table = Table(table_data, colWidths=[1.0*inch, 4.0*inch, 1.5*inch])

                # Create alternating row colors
                table_style = [
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#000000')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 9),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ('FONTSIZE', (0, 1), (-1, -1), 8),
                ]

                # Add alternating row colors (white and light gray)
                for i in range(1, len(table_data)):
                    if i % 2 == 1:
                        table_style.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#FFFFFF')))
                    else:
                        table_style.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#F8F8F8')))

                table.setStyle(TableStyle(table_style))
                story.append(table)
                story.append(Spacer(1, 0.1 * inch))

            story.append(Spacer(1, 0.2 * inch))


        # Supply Calendar section
        supply_calendar = report_data.get('supply_calendar', {})
        if supply_calendar:
            story.append(Paragraph('Treasury Supply Calendar', self.styles['SectionHeader']))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#FF4458'), spaceBefore=3, spaceAfter=12))

            for day, events in supply_calendar.items():
                # Day header
                day_header = Paragraph(f"<b>{day}</b>", self.styles['Normal'])
                story.append(day_header)

                # Create table for this day
                table_data = [['Time NY', 'Description', 'Size (bn)']]  # Headers
                for event in events:
                    table_data.append([
                        event['time'],
                        event['description'],
                        event['size']
                    ])

                table = Table(table_data, colWidths=[1.0*inch, 4.0*inch, 1.5*inch])

                # Create alternating row colors
                table_style = [
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#000000')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 9),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ('FONTSIZE', (0, 1), (-1, -1), 8),
                ]

                # Add alternating row colors (white and light gray)
                for i in range(1, len(table_data)):
                    if i % 2 == 1:
                        table_style.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#FFFFFF')))
                    else:
                        table_style.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#F8F8F8')))

                table.setStyle(TableStyle(table_style))
                story.append(table)
                story.append(Spacer(1, 0.1 * inch))

            story.append(Spacer(1, 0.2 * inch))


        # Details section (start on new page)
        details = report_data.get('details', [])
        if details:
            story.append(PageBreak())
            story.append(Paragraph('Detailed Records', self.styles['SectionHeader']))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#FF4458'), spaceBefore=3, spaceAfter=12))

            # Create table from details with smaller font and adjusted columns
            table_data = []
            if details:
                # Header row
                headers = list(details[0].keys())
                table_data.append([h.replace('_', ' ').title() for h in headers])

                # Data rows - truncate long text to fit
                for record in details:
                    row = []
                    for h in headers:
                        value = str(record.get(h, ''))
                        # Truncate document_name if too long
                        if h == 'document_name' and len(value) > 40:
                            value = value[:40] + '...'
                        row.append(value)
                    table_data.append(row)

                # Auto-calculate column widths based on available space
                table = Table(table_data)

                # Create alternating row colors
                table_style = [
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#000000')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 8),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ('FONTSIZE', (0, 1), (-1, -1), 7),
                ]

                # Add alternating row colors (white and light gray)
                for i in range(1, len(table_data)):
                    if i % 2 == 1:
                        table_style.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#FFFFFF')))
                    else:
                        table_style.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#F8F8F8')))

                table.setStyle(TableStyle(table_style))
                story.append(table)

        story.append(Spacer(1, 0.3 * inch))

        # Summary section (start on new page)
        story.append(PageBreak())
        story.append(Paragraph('Summary', self.styles['SectionHeader']))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#FF4458'), spaceBefore=3, spaceAfter=12))
        summary = report_data.get('summary', {})

        for key, value in summary.items():
            if isinstance(value, dict):
                # Handle nested summaries (like category breakdown)
                story.append(Paragraph(f"<b>{key.replace('_', ' ').title()}:</b>", self.styles['Normal']))
                for sub_key, sub_value in value.items():
                    story.append(Paragraph(f"&nbsp;&nbsp;&nbsp;&nbsp;{sub_key}: {sub_value}", self.styles['Normal']))
            else:
                story.append(Paragraph(f"<b>{key.replace('_', ' ').title()}:</b> {value}", self.styles['Normal']))

        # Build PDF
        doc.build(story)
        return filepath
