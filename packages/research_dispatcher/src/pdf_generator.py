from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
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
            with open(path, 'r') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            try:
                script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                full_path = os.path.join(script_dir, path)
                with open(full_path, 'r') as f:
                    return yaml.safe_load(f)
            except FileNotFoundError:
                print(f"Warning: {path} not found, using default colors")
                return {}

    def _get_font(self, weight: str = 'normal') -> str:
        """Get font name from YAML config."""
        font_family = self.format_rules.get('FONT_FAMILY', {})
        base = font_family.get('body', 'Helvetica')
        if weight == 'bold':
            return f"{base}-Bold"
        elif weight == 'italic':
            return f"{base}-Oblique"
        elif weight == 'bold-italic':
            return f"{base}-BoldOblique"
        return base

    def _get_heading_font(self, weight: str = 'bold') -> str:
        """Get heading font name from YAML config."""
        font_family = self.format_rules.get('FONT_FAMILY', {})
        base = font_family.get('heading', 'Helvetica')
        if weight == 'bold':
            return f"{base}-Bold"
        return base

    def _setup_custom_styles(self):
        """Create custom paragraph styles dynamically from format_rules.yaml."""
        title_config = self.format_rules.get('TITLE', [{}])[0]
        h1_config = self.format_rules.get('H1_HEADING', [{}])[0]
        h2_config = self.format_rules.get('H2_HEADING', [{}])[0]
        normal_config = self.format_rules.get('NORMAL_TEXT', [{}])[0]
        minimalist_config = self.format_rules.get('MINIMALIST_TEXT', [{}])[0]
        accent_config = self.format_rules.get('ACCENT_TEXT', [{}])[0]
        theme_header_config = self.format_rules.get('THEME_HEADER', [{}])[0]
        callout_quote_config = self.format_rules.get('CALLOUT_QUOTE', [{}])[0]
        callout_attr_config = self.format_rules.get('CALLOUT_ATTRIBUTION', [{}])[0]
        feedback_config = self.format_rules.get('FEEDBACK_LINKS', [{}])[0]
        indented_config = self.format_rules.get('INDENTED_BODY', [{}])[0]
        summary_stat_config = self.format_rules.get('SUMMARY_STAT', [{}])[0]
        summary_label_config = self.format_rules.get('SUMMARY_STAT_LABEL', [{}])[0]

        # Set leading on base Normal style
        self.styles['Normal'].leading = normal_config.get('leading', 18)

        # Title style
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=title_config.get('font_size', 48),
            textColor=colors.HexColor(title_config.get('font_color', '#000000')),
            spaceAfter=title_config.get('space_after', 40),
            spaceBefore=title_config.get('space_before', 20),
            alignment=TA_CENTER,
            fontName=self._get_heading_font('bold')
        ))

        # H1 Section Header
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self.styles['Heading2'],
            fontSize=h1_config.get('font_size', 28),
            textColor=colors.HexColor(h1_config.get('font_color', '#000000')),
            spaceAfter=h1_config.get('space_after', 20),
            spaceBefore=h1_config.get('space_before', 30),
            leading=h1_config.get('leading', 34),
            fontName=self._get_heading_font('bold')
        ))

        # H2 Subsection Header
        self.styles.add(ParagraphStyle(
            name='SubsectionHeader',
            parent=self.styles['Heading2'],
            fontSize=h2_config.get('font_size', 20),
            textColor=colors.HexColor(h2_config.get('font_color', '#000000')),
            spaceAfter=h2_config.get('space_after', 16),
            spaceBefore=h2_config.get('space_before', 16),
            leading=h2_config.get('leading', 26),
            fontName=self._get_heading_font('bold')
        ))

        # Accent style for small labels (coral red)
        self.styles.add(ParagraphStyle(
            name='Accent',
            parent=self.styles['Normal'],
            fontSize=accent_config.get('font_size', 9),
            textColor=colors.HexColor(accent_config.get('font_color', '#FF4458')),
            spaceAfter=accent_config.get('space_after', 6),
            spaceBefore=accent_config.get('space_before', 0),
            fontName=self._get_font('bold')
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

        # Theme header — YAML-driven at 13pt
        self.styles.add(ParagraphStyle(
            name='ThemeHeader',
            parent=self.styles['Normal'],
            fontSize=theme_header_config.get('font_size', 13),
            textColor=colors.HexColor(theme_header_config.get('font_color', '#000000')),
            spaceAfter=theme_header_config.get('space_after', 4),
            spaceBefore=theme_header_config.get('space_before', 6),
            fontName=self._get_font('bold')
        ))

        # Callout quote style — YAML-driven with generous leading
        self.styles.add(ParagraphStyle(
            name='CalloutQuote',
            parent=self.styles['Normal'],
            fontSize=callout_quote_config.get('font_size', 12),
            textColor=colors.HexColor(callout_quote_config.get('font_color', '#333333')),
            fontName=self._get_font('italic'),
            leading=callout_quote_config.get('leading', 20),
            spaceAfter=callout_quote_config.get('space_after', 4)
        ))

        # Callout attribution style — YAML-driven
        self.styles.add(ParagraphStyle(
            name='CalloutAttribution',
            parent=self.styles['Normal'],
            fontSize=callout_attr_config.get('font_size', 9),
            textColor=colors.HexColor(callout_attr_config.get('font_color', '#666666')),
            fontName=self._get_font(),
            alignment=TA_RIGHT
        ))

        # Feedback links style — YAML-driven
        self.styles.add(ParagraphStyle(
            name='FeedbackLinks',
            parent=self.styles['Normal'],
            fontSize=feedback_config.get('font_size', 8),
            textColor=colors.HexColor(feedback_config.get('font_color', '#666666')),
            spaceAfter=feedback_config.get('space_after', 8),
            spaceBefore=feedback_config.get('space_before', 2),
            leftIndent=indented_config.get('left_indent', 18)
        ))

        # Indented body text — replaces &nbsp; indentation
        self.styles.add(ParagraphStyle(
            name='IndentedBody',
            parent=self.styles['Normal'],
            fontSize=indented_config.get('font_size', 11),
            textColor=colors.HexColor(indented_config.get('font_color', '#000000')),
            leftIndent=indented_config.get('left_indent', 18),
            leading=indented_config.get('leading', 18),
            spaceAfter=indented_config.get('space_after', 6),
            spaceBefore=indented_config.get('space_before', 2)
        ))

        # Conviction color styles
        conviction_high = self.format_rules.get('CONVICTION_HIGH', [{}])[0]
        conviction_med = self.format_rules.get('CONVICTION_MEDIUM', [{}])[0]
        conviction_low = self.format_rules.get('CONVICTION_LOW', [{}])[0]

        self.styles.add(ParagraphStyle(
            name='ConvictionHigh',
            parent=self.styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor(conviction_high.get('color', '#00875A')),
            fontName=self._get_font('bold'),
            spaceAfter=2,
            spaceBefore=0
        ))

        self.styles.add(ParagraphStyle(
            name='ConvictionMedium',
            parent=self.styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor(conviction_med.get('color', '#FF8B00')),
            fontName=self._get_font('bold'),
            spaceAfter=2,
            spaceBefore=0
        ))

        self.styles.add(ParagraphStyle(
            name='ConvictionLow',
            parent=self.styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor(conviction_low.get('color', '#999999')),
            fontName=self._get_font('bold'),
            spaceAfter=2,
            spaceBefore=0
        ))

        # Summary stat styles
        self.styles.add(ParagraphStyle(
            name='SummaryStat',
            parent=self.styles['Normal'],
            fontSize=summary_stat_config.get('font_size', 14),
            textColor=colors.HexColor(summary_stat_config.get('font_color', '#000000')),
            fontName=self._get_font('bold'),
            alignment=TA_CENTER,
            spaceAfter=0,
            spaceBefore=0
        ))

        self.styles.add(ParagraphStyle(
            name='SummaryStatLabel',
            parent=self.styles['Normal'],
            fontSize=summary_label_config.get('font_size', 8),
            textColor=colors.HexColor(summary_label_config.get('font_color', '#999999')),
            alignment=TA_CENTER,
            spaceAfter=0,
            spaceBefore=0
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
        """Create feedback links HTML for a theme or through-line."""
        feedback_url = Config.FEEDBACK_BASE_URL
        if not feedback_url or not doc_id:
            return ""

        viewer_url = Config.DOCUMENT_VIEWER_URL
        token = self._sign_document_link(doc_id)

        useful_url = f"{feedback_url}?{urlencode({'doc': doc_id, 'item': item_id, 'action': 'useful'})}"
        flag_url = f"{feedback_url}?{urlencode({'doc': doc_id, 'item': item_id, 'action': 'flag'})}"
        view_params = {'id': doc_id}
        if token:
            view_params['token'] = token
        view_url = f"{viewer_url}?{urlencode(view_params)}"

        return (
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

    def _get_conviction_style(self, conviction: str) -> str:
        """Map conviction string to a style name."""
        conviction_lower = conviction.strip().lower() if conviction else ''
        if conviction_lower == 'high':
            return 'ConvictionHigh'
        elif conviction_lower in ('medium', 'moderate'):
            return 'ConvictionMedium'
        return 'ConvictionLow'

    def _get_conviction_color(self, conviction: str) -> str:
        """Map conviction string to a hex color for inline use."""
        conviction_lower = conviction.strip().lower() if conviction else ''
        if conviction_lower == 'high':
            return self.format_rules.get('CONVICTION_HIGH', [{}])[0].get('color', '#00875A')
        elif conviction_lower in ('medium', 'moderate'):
            return self.format_rules.get('CONVICTION_MEDIUM', [{}])[0].get('color', '#FF8B00')
        return self.format_rules.get('CONVICTION_LOW', [{}])[0].get('color', '#999999')

    def _create_callout_box(self, callout: Dict[str, Any]) -> list:
        """Create a styled callout box with coral red left border."""
        elements = []

        quote_text = f'"{callout["text"]}"'
        quote_para = Paragraph(quote_text, self.styles['CalloutQuote'])

        source_label = callout.get("source", "Multiple")
        if "," in source_label or source_label == "Multiple":
            attribution = f"— Sources: {source_label}"
        else:
            attribution = f"— {source_label}"
        attr_para = Paragraph(attribution, self.styles['CalloutAttribution'])

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

        border_cell = Table([['']], colWidths=[4], rowHeights=[None])
        border_cell.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#FF4458')),
        ]))

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

    def _create_through_line_card(self, tl: Dict[str, Any]) -> list:
        """Create a through-line card block with gray background and coral left border."""
        elements = []
        card_bg = self.format_rules.get('THROUGH_LINE_CARD', [{}])[0].get('background_color', '#F9F9F9')

        card_rows = []

        # Lead in bold
        if tl.get('lead'):
            lead_para = Paragraph(f"<b>{tl['lead']}</b>", self.styles['Normal'])
            card_rows.append([lead_para])

        # Key insight indented
        if tl.get('key_insight'):
            insight_para = Paragraph(tl['key_insight'], self.styles['IndentedBody'])
            card_rows.append([insight_para])

        # Tag line (themes, trades, sources) in minimalist style
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
            tag_para = Paragraph(f"<i>{tag_line}</i>", self.styles['Minimalist'])
            card_rows.append([tag_para])

        # Feedback links
        doc_id = tl.get('doc_id', '')
        item_id = tl.get('item_id', '')
        if doc_id and item_id:
            feedback_links = self._create_feedback_links(doc_id, item_id)
            if feedback_links:
                card_rows.append([Paragraph(feedback_links, self.styles['FeedbackLinks'])])

        if not card_rows:
            return elements

        # Content table
        content_width = 6.5 * inch
        margins = self.format_rules.get('PAGE_MARGINS', {})
        page_width = letter[0] / 72  # letter width in inches
        available = page_width - margins.get('left', 0.75) - margins.get('right', 0.75)
        content_width = (available - 0.1) * inch  # subtract border width

        content_table = Table(card_rows, colWidths=[content_width])
        content_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (0, 0), 10),
            ('BOTTOMPADDING', (0, -1), (0, -1), 10),
            ('TOPPADDING', (0, 1), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -2), 2),
        ]))

        # Coral left border cell
        border_cell = Table([['']], colWidths=[4], rowHeights=[None])
        border_cell.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#FF4458')),
        ]))

        # Combine border and content
        card_table = Table(
            [[border_cell, content_table]],
            colWidths=[4, content_width]
        )
        card_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BACKGROUND', (1, 0), (1, 0), colors.HexColor(card_bg)),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))

        elements.append(Spacer(1, 0.1 * inch))
        elements.append(card_table)
        elements.append(Spacer(1, 0.15 * inch))

        return elements

    def _create_summary_stats_bar(self, report_data: Dict[str, Any]) -> list:
        """Create a compact horizontal stats bar for page 1."""
        elements = []
        summary = report_data.get('summary', {})

        total_docs = summary.get('total_documents', 0)
        sources = summary.get('by_source', {})
        num_sources = len(sources)

        # Date range display
        source_date_range = report_data.get('source_date_range')
        date_display = ''
        if source_date_range:
            start = source_date_range.get('start', '')
            end = source_date_range.get('end', '')
            if start and end:
                date_display = self._format_date_range(start, end)

        # Build stat cells: each is a mini table with number on top, label below
        stat_cells = []

        stat_items = [
            (str(total_docs), 'Documents'),
            (str(num_sources), 'Sources'),
        ]
        if date_display:
            stat_items.append((date_display, 'Date Range'))

        for value, label in stat_items:
            val_para = Paragraph(value, self.styles['SummaryStat'])
            label_para = Paragraph(label, self.styles['SummaryStatLabel'])
            cell_table = Table([[val_para], [label_para]], colWidths=[2.0 * inch])
            cell_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
            stat_cells.append(cell_table)

        if not stat_cells:
            return elements

        col_width = 2.0 * inch
        stats_table = Table([stat_cells], colWidths=[col_width] * len(stat_cells))
        stats_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F5F5F5')),
            ('LINEAFTER', (0, 0), (-2, -1), 0.5, colors.HexColor('#DDDDDD')),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))

        elements.append(Spacer(1, 0.15 * inch))
        elements.append(stats_table)
        elements.append(Spacer(1, 0.15 * inch))

        return elements

    def generate(self, report_data: Dict[str, Any], filename: str = 'report.pdf') -> str:
        """Generate PDF from report data."""
        filepath = os.path.join(self.output_dir, filename)

        # Read page margins from YAML
        margins = self.format_rules.get('PAGE_MARGINS', {})
        doc = SimpleDocTemplate(
            filepath,
            pagesize=letter,
            leftMargin=margins.get('left', 0.75) * inch,
            rightMargin=margins.get('right', 0.75) * inch,
            topMargin=margins.get('top', 1.0) * inch,
            bottomMargin=margins.get('bottom', 0.75) * inch,
        )
        story = []

        # Get callouts and index by source_through_line for positioning
        callouts = report_data.get('callouts', [])
        callouts_by_through_line = {}
        for callout in callouts:
            source_tl = callout.get('source_through_line', '')
            if source_tl:
                callouts_by_through_line[source_tl] = callout

        def get_callout_for_through_line(lead):
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

        # Active filters banner
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

        # Summary stats bar on page 1
        story.extend(self._create_summary_stats_bar(report_data))

        story.append(Spacer(1, 0.3 * inch))

        # Through Lines section — rendered as card blocks
        through_lines = report_data.get('through_lines', [])
        if through_lines:
            story.append(Paragraph('Through Lines', self.styles['SectionHeader']))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#FF4458'), spaceBefore=3, spaceAfter=12))

            for tl in through_lines:
                # Render through-line as a card block
                story.extend(self._create_through_line_card(tl))

                # Insert callout if one is associated with this through-line
                if tl.get('lead'):
                    story.extend(get_callout_for_through_line(tl['lead']))

            story.append(Spacer(1, 0.2 * inch))

        # Themes Analysis section
        themes_by_through_line = report_data.get('themes_by_through_line', [])
        themes_analysis = report_data.get('themes_analysis', [])
        if themes_by_through_line:
            story.append(PageBreak())
            story.append(Paragraph('Thematic Analysis', self.styles['SectionHeader']))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#FF4458'), spaceBefore=3, spaceAfter=12))

            for group in themes_by_through_line:
                lead = group.get('lead', 'Theme Cluster')
                story.append(Paragraph(lead, self.styles['SubsectionHeader']))

                for theme in group.get('themes', []):
                    count = theme['count']
                    if count >= 2:
                        theme_title = f"<b>{theme['label']}</b> ({count} occurrences)"
                    else:
                        theme_title = f"<b>{theme['label']}</b>"
                    story.append(Paragraph(theme_title, self.styles['ThemeHeader']))

                    examples = theme.get('examples', [])
                    for example in examples:
                        context = example.get('context', '')
                        if context:
                            if example.get('show_document', True):
                                doc_name = example.get('document', 'Unknown')
                                # Two-column: context left, doc name right
                                ctx_para = Paragraph(context, self.styles['IndentedBody'])
                                doc_para = Paragraph(f"<i>{doc_name}</i>", self.styles['Minimalist'])
                                attr_table = Table(
                                    [[ctx_para, doc_para]],
                                    colWidths=[5.0 * inch, 1.5 * inch]
                                )
                                attr_table.setStyle(TableStyle([
                                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                    ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
                                    ('LEFTPADDING', (0, 0), (0, 0), 18),
                                    ('LEFTPADDING', (1, 0), (1, 0), 4),
                                    ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                                    ('TOPPADDING', (0, 0), (-1, -1), 2),
                                    ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                                ]))
                                story.append(attr_table)
                            else:
                                story.append(Paragraph(context, self.styles['IndentedBody']))

                            # Add feedback links
                            doc_id = example.get('doc_id', '')
                            item_id = example.get('item_id', '')
                            if doc_id and item_id:
                                feedback_links = self._create_feedback_links(doc_id, item_id)
                                if feedback_links:
                                    story.append(Paragraph(feedback_links, self.styles['FeedbackLinks']))

                    story.append(Spacer(1, 0.15 * inch))

                story.append(Spacer(1, 0.2 * inch))
        elif themes_analysis:
            story.append(PageBreak())
            story.append(Paragraph('Thematic Analysis', self.styles['SectionHeader']))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#FF4458'), spaceBefore=3, spaceAfter=12))

            for theme in themes_analysis:
                count = theme['count']
                if count >= 2:
                    theme_title = f"<b>{theme['label']}</b> ({count} occurrences)"
                else:
                    theme_title = f"<b>{theme['label']}</b>"
                story.append(Paragraph(theme_title, self.styles['ThemeHeader']))

                examples = theme.get('examples', [])
                for example in examples:
                    context = example.get('context', '')
                    if context:
                        if example.get('show_document', True):
                            doc_name = example.get('document', 'Unknown')
                            ctx_para = Paragraph(context, self.styles['IndentedBody'])
                            doc_para = Paragraph(f"<i>{doc_name}</i>", self.styles['Minimalist'])
                            attr_table = Table(
                                [[ctx_para, doc_para]],
                                colWidths=[5.0 * inch, 1.5 * inch]
                            )
                            attr_table.setStyle(TableStyle([
                                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
                                ('LEFTPADDING', (0, 0), (0, 0), 18),
                                ('LEFTPADDING', (1, 0), (1, 0), 4),
                                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                                ('TOPPADDING', (0, 0), (-1, -1), 2),
                                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                            ]))
                            story.append(attr_table)
                        else:
                            story.append(Paragraph(context, self.styles['IndentedBody']))

                        doc_id = example.get('doc_id', '')
                        item_id = example.get('item_id', '')
                        if doc_id and item_id:
                            feedback_links = self._create_feedback_links(doc_id, item_id)
                            if feedback_links:
                                story.append(Paragraph(feedback_links, self.styles['FeedbackLinks']))

                story.append(Spacer(1, 0.15 * inch))

            story.append(Spacer(1, 0.2 * inch))


        # Trades section — with conviction color coding
        trades = report_data.get('trades', [])
        if trades:
            story.append(PageBreak())
            story.append(Paragraph('Trade Recommendations', self.styles['SectionHeader']))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#FF4458'), spaceBefore=3, spaceAfter=12))

            for trade in trades:
                # Conviction colored label before trade text
                conviction = trade['conviction']
                conviction_color = self._get_conviction_color(conviction)
                conviction_label = conviction.upper() if conviction else 'N/A'
                trade_header = f'<font color="{conviction_color}"><b>[{conviction_label}]</b></font> <b>{trade["text"]}</b>'
                story.append(Paragraph(trade_header, self.styles['Normal']))

                # Trade details using IndentedBody
                details_line = f"<i>Exposure: {trade['exposure']} | Timeframe: {trade['timeframe']}</i>"
                story.append(Paragraph(details_line, self.styles['IndentedBody']))

                # Rationale
                if trade.get('rationale'):
                    story.append(Paragraph(trade['rationale'], self.styles['IndentedBody']))

                # Trigger levels
                if trade.get('trigger_levels'):
                    story.append(Paragraph(f"<i>Triggers: {trade['trigger_levels']}</i>", self.styles['IndentedBody']))

                # Source document
                doc_text = trade['document'][:80] + ('...' if len(trade['document']) > 80 else '')
                source_info = f"<i>Source: {trade['source']} - {doc_text} ({trade['date']})</i>"
                story.append(Paragraph(source_info, self.styles['IndentedBody']))

                story.append(Spacer(1, 0.15 * inch))

            story.append(Spacer(1, 0.2 * inch))


        # Economic Calendar section
        economic_calendar = report_data.get('economic_calendar', {})
        if economic_calendar:
            story.append(PageBreak())
            story.append(Paragraph('Economic Calendar', self.styles['SectionHeader']))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#FF4458'), spaceBefore=3, spaceAfter=12))

            for day, events in economic_calendar.items():
                day_header = Paragraph(f"<b>{day}</b>", self.styles['Normal'])
                story.append(day_header)

                table_data = [['Time NY', 'Event', 'Consensus']]
                for event in events:
                    table_data.append([
                        event['time'],
                        event['event'],
                        event['consensus']
                    ])

                table = Table(table_data, colWidths=[1.0*inch, 4.0*inch, 1.5*inch])

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
            story.append(PageBreak())
            story.append(Paragraph('Treasury Supply Calendar', self.styles['SectionHeader']))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#FF4458'), spaceBefore=3, spaceAfter=12))

            for day, events in supply_calendar.items():
                day_header = Paragraph(f"<b>{day}</b>", self.styles['Normal'])
                story.append(day_header)

                table_data = [['Time NY', 'Description', 'Size (bn)']]
                for event in events:
                    table_data.append([
                        event['time'],
                        event['description'],
                        event['size']
                    ])

                table = Table(table_data, colWidths=[1.0*inch, 4.0*inch, 1.5*inch])

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

                for i in range(1, len(table_data)):
                    if i % 2 == 1:
                        table_style.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#FFFFFF')))
                    else:
                        table_style.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#F8F8F8')))

                table.setStyle(TableStyle(table_style))
                story.append(table)
                story.append(Spacer(1, 0.1 * inch))

            story.append(Spacer(1, 0.2 * inch))


        # Details section
        details = report_data.get('details', [])
        if details:
            story.append(PageBreak())
            story.append(Paragraph('Detailed Records', self.styles['SectionHeader']))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#FF4458'), spaceBefore=3, spaceAfter=12))

            table_data = []
            if details:
                headers = list(details[0].keys())
                table_data.append([h.replace('_', ' ').title() for h in headers])

                for record in details:
                    row = []
                    for h in headers:
                        value = str(record.get(h, ''))
                        if h == 'document_name' and len(value) > 40:
                            value = value[:40] + '...'
                        row.append(value)
                    table_data.append(row)

                table = Table(table_data)

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

                for i in range(1, len(table_data)):
                    if i % 2 == 1:
                        table_style.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#FFFFFF')))
                    else:
                        table_style.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#F8F8F8')))

                table.setStyle(TableStyle(table_style))
                story.append(table)

        story.append(Spacer(1, 0.3 * inch))

        # Summary section — remaining nested dict data as a compact footer
        summary = report_data.get('summary', {})
        has_nested = any(isinstance(v, dict) for v in summary.values())
        if has_nested:
            story.append(Paragraph('Summary Detail', self.styles['SubsectionHeader']))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#FF4458'), spaceBefore=3, spaceAfter=12))
            for key, value in summary.items():
                if isinstance(value, dict):
                    story.append(Paragraph(f"<b>{key.replace('_', ' ').title()}:</b>", self.styles['Normal']))
                    for sub_key, sub_value in value.items():
                        story.append(Paragraph(f"{sub_key}: {sub_value}", self.styles['IndentedBody']))

        # Build PDF
        doc.build(story)
        return filepath
