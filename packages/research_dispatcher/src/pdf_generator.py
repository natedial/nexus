from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from typing import Dict, Any
import os
import yaml


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

        # Title style
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=title_config.get('font_size', 32),
            textColor=colors.HexColor(title_config.get('font_color', '#ff2a6d')),
            backColor=colors.HexColor(title_bg_config.get('color', '#133e7c')),
            spaceAfter=title_config.get('space_after', 30),
            spaceBefore=title_config.get('space_before', 30),
            alignment=TA_CENTER,
            leftIndent=6,
            rightIndent=6,
            borderPadding=(8, 4, 24, 4)  # top, right, bottom, left padding
        ))

        # H1 Section Header (main sections)
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self.styles['Heading2'],
            fontSize=h1_config.get('font_size', 24),
            textColor=colors.HexColor(h1_config.get('font_color', '#d1f7ff')),
            backColor=colors.HexColor(h1_bg_config.get('color', '#005678')),
            spaceAfter=h1_config.get('space_after', 12),
            spaceBefore=h1_config.get('space_before', 12),
            leftIndent=6,
            rightIndent=6,
            borderPadding=(8, 4, 12, 4)  # top, right, bottom, left padding
        ))

        # H2 Subsection Header
        self.styles.add(ParagraphStyle(
            name='SubsectionHeader',
            parent=self.styles['Heading2'],
            fontSize=h2_config.get('font_size', 18),
            textColor=colors.HexColor(h2_config.get('font_color', '#333333')),
            backColor=colors.HexColor(h2_bg_config.get('color', '#e0e0e0')),
            spaceAfter=h2_config.get('space_after', 12),
            spaceBefore=h2_config.get('space_before', 12),
            leftIndent=6,
            rightIndent=6,
            borderPadding=(6, 4, 8, 4)  # top, right, bottom, left padding
        ))

        # Minimalist style for timestamps and metadata
        self.styles.add(ParagraphStyle(
            name='Minimalist',
            parent=self.styles['Normal'],
            fontSize=minimalist_config.get('font_size', 9),
            textColor=colors.HexColor(minimalist_config.get('font_color', '#666666')),
            spaceAfter=minimalist_config.get('space_after', 6),
            spaceBefore=minimalist_config.get('space_before', 0)
        ))

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

        # Title
        title = Paragraph(report_data['title'], self.styles['CustomTitle'])
        story.append(title)

        # Generation timestamp
        timestamp = Paragraph(f"Generated: {report_data['generated_at']}", self.styles['Minimalist'])
        story.append(timestamp)
        story.append(Spacer(1, 0.3 * inch))

        # Through Lines section
        through_lines = report_data.get('through_lines', [])
        if through_lines:
            story.append(Paragraph('Through Lines', self.styles['SectionHeader']))

            for tl in through_lines:
                # Lead
                if tl.get('lead'):
                    lead_text = f"<b>{tl['lead']}</b>"
                    story.append(Paragraph(lead_text, self.styles['Normal']))

                # Key insight
                if tl.get('key_insight'):
                    story.append(Paragraph(f"&nbsp;&nbsp;&nbsp;&nbsp;{tl['key_insight']}", self.styles['Normal']))

                # Supporting themes
                if tl.get('supporting_themes'):
                    themes_list = ', '.join(tl['supporting_themes'])
                    story.append(Paragraph(f"&nbsp;&nbsp;&nbsp;&nbsp;<i>Themes: {themes_list}</i>", self.styles['Normal']))

                # Supporting trades
                if tl.get('supporting_trades'):
                    trades_list = ', '.join(tl['supporting_trades'])
                    story.append(Paragraph(f"&nbsp;&nbsp;&nbsp;&nbsp;<i>Related trades: {trades_list}</i>", self.styles['Normal']))

                # Source document
                source_info = f"&nbsp;&nbsp;&nbsp;&nbsp;<i>Source: {tl['source']} - {tl['document'][:80]}{'...' if len(tl['document']) > 80 else ''}</i>"
                story.append(Paragraph(source_info, self.styles['Normal']))

                story.append(Spacer(1, 0.15 * inch))

            story.append(Spacer(1, 0.2 * inch))

        # Themes Analysis section (moved to top)
        themes_analysis = report_data.get('themes_analysis', [])
        if themes_analysis:
            story.append(Paragraph('Top Themes Analysis', self.styles['SectionHeader']))

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

                story.append(Spacer(1, 0.15 * inch))

            story.append(Spacer(1, 0.2 * inch))

        # Trades section
        trades = report_data.get('trades', [])
        if trades:
            story.append(Paragraph('Trades', self.styles['SectionHeader']))

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

        # Details section
        details = report_data.get('details', [])
        if details:
            story.append(Paragraph('Detailed Records', self.styles['SectionHeader']))

            # Create table from details
            table_data = []
            if details:
                # Header row
                headers = list(details[0].keys())
                table_data.append([h.replace('_', ' ').title() for h in headers])

                # Data rows
                for record in details:
                    row = [str(record.get(h, '')) for h in headers]
                    table_data.append(row)

                table = Table(table_data)
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    ('FONTSIZE', (0, 1), (-1, -1), 8),
                ]))
                story.append(table)

        story.append(Spacer(1, 0.3 * inch))

        # Summary section (moved to bottom)
        story.append(Paragraph('Summary', self.styles['SectionHeader']))
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
