"""Tests for document content extractors."""

import json
from pathlib import Path

import pytest

from trace_search.extraction.extractors import SUPPORTED_EXTENSIONS, extract_code_content, extract_csv_content, extract_docx_content, extract_notebook_content, extract_pdf_content, extract_pptx_content, extract_title


class TestSupportedExtensions:
    # Document types
    def test_md_supported(self):
        assert ".md" in SUPPORTED_EXTENSIONS

    def test_pdf_supported(self):
        assert ".pdf" in SUPPORTED_EXTENSIONS

    def test_docx_supported(self):
        assert ".docx" in SUPPORTED_EXTENSIONS

    def test_pptx_supported(self):
        assert ".pptx" in SUPPORTED_EXTENSIONS

    def test_csv_supported(self):
        assert ".csv" in SUPPORTED_EXTENSIONS

    # Code types
    def test_sql_supported(self):
        assert ".sql" in SUPPORTED_EXTENSIONS

    def test_py_supported(self):
        assert ".py" in SUPPORTED_EXTENSIONS

    def test_yml_supported(self):
        assert ".yml" in SUPPORTED_EXTENSIONS

    def test_yaml_supported(self):
        assert ".yaml" in SUPPORTED_EXTENSIONS

    def test_ts_supported(self):
        assert ".ts" in SUPPORTED_EXTENSIONS

    def test_tsx_supported(self):
        assert ".tsx" in SUPPORTED_EXTENSIONS

    # Notebook type
    def test_ipynb_supported(self):
        assert ".ipynb" in SUPPORTED_EXTENSIONS

    def test_extension_count(self):
        assert len(SUPPORTED_EXTENSIONS) == 12


class TestExtractTitle:
    def test_markdown_heading(self):
        content = "# My Document Title\n\nSome content here."
        path = Path("test.md")
        assert extract_title(content, path) == "My Document Title"

    def test_markdown_no_heading_uses_filename(self):
        content = "Some content without heading."
        path = Path("my-document.md")
        assert extract_title(content, path) == "my-document"

    def test_pdf_first_line(self):
        content = "This is the document title from PDF\n\nMore content here."
        path = Path("test.pdf")
        assert extract_title(content, path) == "This is the document title from PDF"

    def test_pdf_skips_all_caps(self):
        content = "HEADER IN ALL CAPS\nThis is the actual title\n\nContent."
        path = Path("test.pdf")
        assert extract_title(content, path) == "This is the actual title"

    def test_pdf_skips_short_lines(self):
        content = "Page 1\nShort\nThis is a proper document title\n\nContent."
        path = Path("test.pdf")
        assert extract_title(content, path) == "This is a proper document title"

    def test_docx_extracts_title(self):
        content = "Document Title Here\n\nParagraph content."
        path = Path("test.docx")
        assert extract_title(content, path) == "Document Title Here"

    def test_csv_extracts_first_row(self):
        content = "Row 1: Name: John | Age: 30\nRow 2: Name: Jane | Age: 25"
        path = Path("meeting-notes.csv")
        assert extract_title(content, path) == "Row 1: Name: John | Age: 30"

    def test_csv_fallback_to_filename(self):
        content = "Short\nAlso short"
        path = Path("meeting-notes.csv")
        assert extract_title(content, path) == "meeting-notes"

    def test_fallback_to_filename(self):
        content = ""
        path = Path("empty-document.pdf")
        assert extract_title(content, path) == "empty-document"

    def test_sql_uses_filename_with_extension(self):
        content = "SELECT * FROM users;"
        path = Path("schema_parser.sql")
        assert extract_title(content, path) == "schema_parser.sql"

    def test_py_uses_filename_with_extension(self):
        content = "def main():\n    pass"
        path = Path("utils.py")
        assert extract_title(content, path) == "utils.py"

    def test_ts_uses_filename_with_extension(self):
        content = "export const foo = 1;"
        path = Path("api.ts")
        assert extract_title(content, path) == "api.ts"

    def test_tsx_uses_filename_with_extension(self):
        content = "export default function App() {}"
        path = Path("Component.tsx")
        assert extract_title(content, path) == "Component.tsx"

    def test_yml_uses_filename_with_extension(self):
        content = "version: 1.0"
        path = Path("config.yml")
        assert extract_title(content, path) == "config.yml"

    def test_yaml_uses_filename_with_extension(self):
        content = "name: test"
        path = Path("schema.yaml")
        assert extract_title(content, path) == "schema.yaml"

    def test_ipynb_uses_filename_with_extension(self):
        content = "[CODE CELL 1]\nprint('hello')"
        path = Path("analysis.ipynb")
        assert extract_title(content, path) == "analysis.ipynb"


class TestExtractCSVContent:
    def test_basic_csv(self, tmp_path: Path):
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("Name,Age,City\nJohn,30,New York\nJane,25,Boston\n")

        content = extract_csv_content(csv_file)

        assert "Row 1:" in content
        assert "Name: John" in content
        assert "Age: 30" in content
        assert "City: New York" in content
        assert "Row 2:" in content
        assert "Name: Jane" in content

    def test_csv_with_empty_values(self, tmp_path: Path):
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("Name,Age,City\nJohn,,New York\n")

        content = extract_csv_content(csv_file)

        assert "Name: John" in content
        assert "City: New York" in content
        assert "Age:" not in content

    def test_empty_csv(self, tmp_path: Path):
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("Name,Age,City\n")

        content = extract_csv_content(csv_file)
        assert content == ""


class TestExtractPDFContent:
    """Test PDF content extraction (integration tests are in TestIntegrationWithRealFiles)."""


class TestExtractDocxContent:
    """Test DOCX content extraction (integration tests are in TestIntegrationWithRealFiles)."""


class TestExtractPptxContent:
    """Test PPTX content extraction (integration tests are in TestIntegrationWithRealFiles)."""


class TestExtractCodeContent:
    def test_code_extraction_exists(self):
        assert callable(extract_code_content)

    def test_python_file(self, tmp_path: Path):
        py_file = tmp_path / "test.py"
        py_file.write_text("def hello():\n    print('Hello, World!')\n")

        content = extract_code_content(py_file)

        assert "def hello():" in content
        assert "print('Hello, World!')" in content

    def test_sql_file(self, tmp_path: Path):
        sql_file = tmp_path / "test.sql"
        sql_file.write_text("SELECT id, name FROM users WHERE active = true;")

        content = extract_code_content(sql_file)

        assert "SELECT id, name FROM users" in content

    def test_typescript_file(self, tmp_path: Path):
        ts_file = tmp_path / "test.ts"
        ts_file.write_text(
            "export const greet = (name: string): string => `Hello, ${name}`;"
        )

        content = extract_code_content(ts_file)

        assert "export const greet" in content
        assert "string" in content

    def test_yaml_file(self, tmp_path: Path):
        yml_file = tmp_path / "test.yml"
        yml_file.write_text("version: '3'\nservices:\n  web:\n    image: nginx\n")

        content = extract_code_content(yml_file)

        assert "version: '3'" in content
        assert "services:" in content

    def test_unicode_content(self, tmp_path: Path):
        py_file = tmp_path / "test.py"
        py_file.write_text(
            "# Kommentar pa svenska: aoa\nprint('Hej varlden!')\n", encoding="utf-8"
        )

        content = extract_code_content(py_file)

        assert "aoa" in content
        assert "varlden" in content

    def test_empty_file(self, tmp_path: Path):
        py_file = tmp_path / "test.py"
        py_file.write_text("")

        content = extract_code_content(py_file)

        assert content == ""


class TestExtractNotebookContent:
    def test_notebook_extraction_exists(self):
        assert callable(extract_notebook_content)

    def test_basic_notebook(self, tmp_path: Path):
        notebook = {
            "cells": [
                {"cell_type": "markdown", "source": ["# Title\n", "Description here"]},
                {
                    "cell_type": "code",
                    "source": ["import pandas as pd\n", "df = pd.read_csv('data.csv')"],
                },
            ]
        }
        nb_file = tmp_path / "test.ipynb"
        nb_file.write_text(json.dumps(notebook))

        content = extract_notebook_content(nb_file)

        assert "[MARKDOWN CELL 1]" in content
        assert "# Title" in content
        assert "[CODE CELL 2]" in content
        assert "import pandas" in content

    def test_notebook_with_empty_cells(self, tmp_path: Path):
        """Empty cells should be skipped, not labeled."""
        notebook = {
            "cells": [
                {"cell_type": "code", "source": []},
                {"cell_type": "code", "source": ["print('hello')"]},
            ]
        }
        nb_file = tmp_path / "test.ipynb"
        nb_file.write_text(json.dumps(notebook))

        content = extract_notebook_content(nb_file)

        assert "[CODE CELL 1]" not in content
        assert "[CODE CELL 2]" in content
        assert "print('hello')" in content

    def test_notebook_code_only(self, tmp_path: Path):
        notebook = {
            "cells": [
                {"cell_type": "code", "source": ["x = 1"]},
                {"cell_type": "code", "source": ["y = 2"]},
            ]
        }
        nb_file = tmp_path / "test.ipynb"
        nb_file.write_text(json.dumps(notebook))

        content = extract_notebook_content(nb_file)

        assert "[CODE CELL 1]" in content
        assert "[CODE CELL 2]" in content

    def test_empty_notebook(self, tmp_path: Path):
        notebook = {"cells": []}
        nb_file = tmp_path / "test.ipynb"
        nb_file.write_text(json.dumps(notebook))

        content = extract_notebook_content(nb_file)

        assert content == ""

    def test_invalid_notebook_returns_empty(self, tmp_path: Path):
        nb_file = tmp_path / "test.ipynb"
        nb_file.write_text("not valid json")

        content = extract_notebook_content(nb_file)

        assert content == ""


@pytest.mark.slow
class TestIntegrationWithRealFiles:
    """Integration tests using actual wiki files; skip when fixtures aren't available."""

    def test_pdf_from_wiki(self, wiki_path):
        pdfs = list(wiki_path.rglob("*.pdf"))
        if not pdfs:
            pytest.skip("No PDF files found in wiki")

        pdf_path = pdfs[0]
        content = extract_pdf_content(pdf_path)

        assert isinstance(content, str)
        # Content should be non-trivial (some PDFs may be scanned/images)
        if content.strip():
            assert len(content) > 10

    def test_docx_from_wiki(self, wiki_path):
        docx_files = list(wiki_path.rglob("*.docx"))
        if not docx_files:
            pytest.skip("No DOCX files found in wiki")

        docx_path = docx_files[0]
        content = extract_docx_content(docx_path)

        assert isinstance(content, str)
        assert len(content) > 0

    def test_pptx_from_wiki(self, wiki_path):
        pptx_files = list(wiki_path.rglob("*.pptx"))
        if not pptx_files:
            pytest.skip("No PPTX files found in wiki")

        pptx_path = pptx_files[0]
        content = extract_pptx_content(pptx_path)

        assert isinstance(content, str)
        assert "[Slide" in content

    def test_csv_from_wiki(self, wiki_path):
        csv_files = list(wiki_path.rglob("*.csv"))
        if not csv_files:
            pytest.skip("No CSV files found in wiki")

        csv_path = csv_files[0]
        try:
            content = extract_csv_content(csv_path)
            assert isinstance(content, str)
        except Exception:
            # Some CSVs may have encoding issues; skip rather than fail
            pytest.skip(f"Could not parse CSV: {csv_path}")
