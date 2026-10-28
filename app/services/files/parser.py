"""Парсинг текстовых файлов: txt/md/pdf/docx -> единый текст."""

import logging
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger("parser")

TEXT_EXTS = {".txt", ".md", ".text", ".me"}
PDF_EXTS = {".pdf"}
DOCX_EXTS = {".docx"}


def extract_text(path: str | Path, *, filename: str = "") -> str:
    """Извлекает текст из файла и усекает до MAX_TEXT_CHARS."""
    path = Path(path)
    ext = Path(filename or path.name).suffix.lower()
    text = _extract_by_ext(path, ext)
    if len(text) > settings.MAX_TEXT_CHARS:
        text = text[: settings.MAX_TEXT_CHARS]
    return text.strip()


def _extract_by_ext(path: Path, ext: str) -> str:
    if ext in TEXT_EXTS:
        data = path.read_bytes()
        for enc in ("utf-8", "cp1251", "latin-1"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")

    if ext in PDF_EXTS:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)

    if ext in DOCX_EXTS:
        from docx import Document

        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs)

    raise ValueError(f"Неподдерживаемый формат файла: {ext or 'без расширения'}")
