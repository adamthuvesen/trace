from pathlib import Path

import pytest

from trace_search.extraction.extractors import (
    extract_content,
    extract_title,
)

CODE_FILES = ("schema_parser.sql", "utils.py", "api.ts", "Component.tsx", "config.yml", "s.yaml")


class TestExtractTitle:
    def test_markdown_heading(self):
        assert extract_title("# My Document Title\n\nBody.", Path("test.md")) == "My Document Title"

    def test_markdown_no_heading_uses_filename(self):
        assert extract_title("No heading.", Path("my-document.md")) == "my-document"

    def test_markdown_no_heading_prefers_fallback(self):
        assert extract_title("No heading.", Path("a.md"), fallback="Front") == "Front"

    @pytest.mark.parametrize("filename", CODE_FILES)
    def test_code_uses_filename_with_extension(self, filename: str):
        assert extract_title("# not a heading", Path(filename)) == filename


class TestExtractContent:
    @pytest.mark.parametrize("filename", ("doc.md", *CODE_FILES))
    def test_reads_supported_files_as_text(self, tmp_path: Path, filename: str):
        path = tmp_path / filename
        path.write_text("Kommentar pa svenska: aoa\nSELECT 1;\n", encoding="utf-8")
        assert extract_content(path) == "Kommentar pa svenska: aoa\nSELECT 1;\n"

    def test_empty_file(self, tmp_path: Path):
        path = tmp_path / "test.py"
        path.write_text("")
        assert extract_content(path) == ""

    @pytest.mark.parametrize("filename", ("rows.csv", "analysis.ipynb", "report.pdf"))
    def test_unsupported_extension_raises(self, tmp_path: Path, filename: str):
        path = tmp_path / filename
        path.write_text("x")
        with pytest.raises(ValueError, match="Unsupported file type"):
            extract_content(path)
