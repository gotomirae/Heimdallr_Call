# PRD Ref: §8.7 · 페이지 근거 딥링크와 비파괴 색상 표시 회귀.
from pathlib import Path

import pymupdf
import pytest

from src.analysis.source_evidence import (
    EvidenceMark,
    EvidenceNotFoundError,
    evidence_locator,
    highlight_pdf,
    page_deep_link,
)


def _sample_pdf(path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Revenue growth reached 25 percent")
    document.save(path)
    document.close()


def test_page_link_is_added_only_after_viewer_verification():
    url = "https://example.com/report.pdf?download=1#old"
    assert page_deep_link(url, 7, fragment_verified=True) == (
        "https://example.com/report.pdf?download=1#page=7"
    )
    assert page_deep_link(url, 7, fragment_verified=False) == url


def test_locator_keeps_page_quote_and_verification_state():
    locator = evidence_locator(
        "https://drive.google.com/file/d/abc/view",
        12,
        "  HBM   demand expands  ",
        section="시장 전망",
        fragment_verified=False,
    )
    assert locator["page"] == 12
    assert locator["quote"] == "HBM demand expands"
    assert locator["page_url"] == locator["source_url"]
    assert locator["page_fragment_verified"] is False


def test_highlight_pdf_preserves_original_and_exports_page_preview(tmp_path):
    original = tmp_path / "original.pdf"
    output = tmp_path / "highlighted.pdf"
    previews = tmp_path / "previews"
    _sample_pdf(original)
    before = original.read_bytes()

    manifest = highlight_pdf(
        original,
        output,
        [EvidenceMark(1, "Revenue growth reached 25 percent", "성장률", "yellow")],
        preview_dir=previews,
    )

    assert original.read_bytes() == before
    assert output.exists()
    assert manifest["original_preserved"] is True
    assert manifest["marks"][0]["matches"] == 1
    assert Path(manifest["marks"][0]["preview_path"]).exists()
    marked = pymupdf.open(output)
    assert len(list(marked[0].annots())) == 1
    marked.close()


def test_highlight_pdf_fails_when_exact_evidence_is_absent(tmp_path):
    original = tmp_path / "original.pdf"
    _sample_pdf(original)
    with pytest.raises(EvidenceNotFoundError):
        highlight_pdf(
            original,
            tmp_path / "highlighted.pdf",
            [EvidenceMark(1, "invented evidence", "없는 근거")],
        )
    assert not (tmp_path / "highlighted.pdf").exists()


def test_highlight_pdf_never_overwrites_a_previous_derivative(tmp_path):
    original = tmp_path / "original.pdf"
    output = tmp_path / "highlighted.pdf"
    _sample_pdf(original)
    output.write_bytes(b"previous evidence")
    with pytest.raises(FileExistsError):
        highlight_pdf(
            original,
            output,
            [EvidenceMark(1, "Revenue growth reached 25 percent", "성장률")],
        )
    assert output.read_bytes() == b"previous evidence"
