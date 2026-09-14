import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from config import Config
import os


class EmailSender:
    """Handles sending emails with PDF attachments via SMTP."""

    def __init__(self):
        self.smtp_server = Config.SMTP_SERVER
        self.smtp_port = Config.SMTP_PORT
        self.username = Config.SMTP_USERNAME
        self.password = Config.SMTP_PASSWORD
        self.from_email = Config.EMAIL_FROM

    def send_report(self, pdf_path: str, recipients: str = None, subject: str = None, body: str = None):
        """
        Send email with PDF attachment.

        Args:
            pdf_path: Path to PDF file to attach
            recipients: Email recipients, comma-separated (defaults to config)
            subject: Email subject line
            body: Email body text
        """
        recipients = recipients or Config.EMAIL_TO
        subject = subject or f"{Config.REPORT_TITLE} - {self._get_date()}"
        body = body or f"Please find attached the {Config.REPORT_TITLE}."

        # Parse recipients (comma-separated, with optional spaces)
        recipient_list = [r.strip() for r in recipients.split(',')]

        # Create message
        msg = MIMEMultipart()
        msg['From'] = self.from_email
        msg['To'] = ', '.join(recipient_list)
        msg['Subject'] = subject

        # Add body
        msg.attach(MIMEText(body, 'plain'))

        # Add PDF attachment
        with open(pdf_path, 'rb') as f:
            pdf_attachment = MIMEApplication(f.read(), _subtype='pdf')
            pdf_attachment.add_header(
                'Content-Disposition',
                'attachment',
                filename=os.path.basename(pdf_path)
            )
            msg.attach(pdf_attachment)

        # Send email to all recipients
        with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
            server.starttls()
            server.login(self.username, self.password)
            server.send_message(msg)

        return recipient_list

    @staticmethod
    def _get_date():
        """Get current date formatted for email subject."""
        from datetime import datetime
        return datetime.now().strftime('%Y-%m-%d')
