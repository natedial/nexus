from __future__ import annotations

import base64
from io import BytesIO

from pypdf import PdfWriter


def minimal_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def minimal_pdf_base64() -> str:
    return base64.b64encode(minimal_pdf_bytes()).decode("ascii")
