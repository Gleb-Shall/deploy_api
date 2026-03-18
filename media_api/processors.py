"""
Конвертация файлов:
  PDF  → список PNG (по одному на страницу) через pymupdf
  DOCX → текст (.txt)            через python-docx
"""
import io


class ProcessingError(Exception):
    """Ошибка конвертации файла с сообщением для пользователя."""


def pdf_to_pages(content: bytes, max_pages: int = 50) -> list[tuple[bytes, str]]:
    """
    Конвертирует PDF в список PNG-изображений (по одному на каждую страницу).

    Возвращает [(png_bytes, "image/png"), ...].
    Бросает ProcessingError при невалидном файле или превышении лимита страниц.
    """
    try:
        import fitz  # pymupdf
    except ImportError:
        raise ProcessingError("Сервер не поддерживает конвертацию PDF (pymupdf не установлен)")

    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception:
        raise ProcessingError("Не удалось открыть PDF. Проверьте, что файл не повреждён и не зашифрован")

    page_count = len(doc)
    if page_count == 0:
        doc.close()
        raise ProcessingError("PDF не содержит страниц")

    if page_count > max_pages:
        doc.close()
        raise ProcessingError(f"PDF содержит {page_count} страниц, максимум {max_pages}")

    pages = []
    try:
        for page in doc:
            pixmap = page.get_pixmap(dpi=150)
            pages.append((pixmap.tobytes("png"), "image/png"))
    except Exception as e:
        raise ProcessingError(f"Ошибка при рендеринге страницы PDF: {e}")
    finally:
        doc.close()

    return pages


def docx_to_text(content: bytes) -> tuple[bytes, str]:
    """
    Извлекает текст из DOCX и возвращает (text_bytes, "text/plain").
    Бросает ProcessingError при невалидном файле.
    """
    try:
        from docx import Document
    except ImportError:
        raise ProcessingError("Сервер не поддерживает конвертацию DOCX (python-docx не установлен)")

    try:
        doc = Document(io.BytesIO(content))
    except Exception:
        raise ProcessingError("Не удалось открыть DOCX. Проверьте, что файл не повреждён")

    lines = [para.text for para in doc.paragraphs]
    text = "\n".join(lines)

    return text.encode("utf-8"), "text/plain"
