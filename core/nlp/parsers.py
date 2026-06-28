"""
PDF text extraction for central bank statements.
Uses pdfplumber (preferred) with pdfminer as fallback.
"""


def extract_text_from_pdf(content: bytes) -> str:
    """Extract plain text from PDF bytes. Returns empty string on failure."""
    try:
        import io
        import pdfplumber

        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages[:10]]
            return " ".join(pages).strip()
    except ImportError:
        pass

    try:
        import io
        from pdfminer.high_level import extract_text_to_fp
        from pdfminer.layout import LAParams

        output = io.StringIO()
        extract_text_to_fp(io.BytesIO(content), output, laparams=LAParams())
        return output.getvalue().strip()
    except Exception:
        return ""
