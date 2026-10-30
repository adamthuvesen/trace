"""Shared generated document fixtures."""

from pathlib import Path

import pytest


@pytest.fixture()
def document_kb(tmp_path: Path) -> Path:
    """Generate readable documents without depending on a private knowledge base."""
    import fitz
    from docx import Document
    from pptx import Presentation
    from pptx.util import Inches

    kb = tmp_path / "documents"
    kb.mkdir()
    (kb / "intro.md").write_text("# Format fixture\n\nMarkdown content")
    (kb / "rows.csv").write_text("name,value\nFormat fixture,42\nSecond row,73\n")
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), "Format fixture PDF content")
        pdf.new_page()
        page = pdf.new_page()
        page.insert_text((72, 72), "Second PDF page")
        pdf.save(kb / "report.pdf")
    document = Document()
    document.add_paragraph("Format fixture Word content")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Item"
    table.cell(0, 1).text = "Value"
    table.cell(1, 0).text = "Widget"
    table.cell(1, 1).text = "42"
    document.save(str(kb / "report.docx"))
    slides = Presentation()
    slide = slides.slides.add_slide(slides.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1))
    box.text_frame.text = "Format fixture PowerPoint content"
    table = slide.shapes.add_table(2, 2, Inches(1), Inches(3), Inches(5), Inches(1)).table
    table.cell(0, 0).text = "Metric"
    table.cell(0, 1).text = "Value"
    table.cell(1, 0).text = "Active"
    table.cell(1, 1).text = "7"
    slide.notes_slide.notes_text_frame.text = "Speaker note content"
    slide = slides.slides.add_slide(slides.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1))
    box.text_frame.text = "Final slide text"
    slides.save(str(kb / "report.pptx"))
    return kb
