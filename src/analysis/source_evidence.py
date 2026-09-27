# PRD Ref: §8.7 · SC: 핵심 주장→원문 페이지→색상 표시 근거를 한 번에 검증한다.
"""페이지 단위 원문 근거와 비파괴 PDF 강조 사본을 만든다.

외부 원문이나 사용자의 Drive 원본을 직접 수정하지 않는다. 정확한 페이지와 짧은
근거 문구를 찾은 뒤 별도 PDF와 페이지 PNG를 생성하며, 찾지 못한 문구는 조용히
건너뛰지 않고 실패시킨다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pymupdf


HIGHLIGHT_COLORS: dict[str, tuple[float, float, float]] = {
    "yellow": (1.0, 0.84, 0.0),
    "green": (0.3, 0.85, 0.4),
    "red": (1.0, 0.35, 0.35),
    "blue": (0.35, 0.65, 1.0),
}


@dataclass(frozen=True)
class EvidenceMark:
    page: int
    text: str
    label: str
    color: str = "yellow"


@dataclass(frozen=True)
class HighlightedMark:
    page: int
    text: str
    label: str
    color: str
    matches: int
    preview_path: str | None


class EvidenceNotFoundError(RuntimeError):
    """지정 페이지에서 정확한 근거 문구를 찾지 못했다."""


def page_deep_link(source_url: str, page: int, *, fragment_verified: bool) -> str:
    """검증된 뷰어에만 ``#page=N``을 붙인다.

    Google Drive/Notion 등 일부 뷰어는 fragment를 무시한다. 호출자가 실제 이동을
    검증하지 않았다면 원문 URL을 그대로 돌려주어 가짜 딥링크를 만들지 않는다.
    """
    if page < 1:
        raise ValueError("page는 1 이상이어야 한다")
    if not fragment_verified:
        return source_url
    parsed = urlsplit(source_url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, f"page={page}"))


def evidence_locator(
    source_url: str,
    page: int,
    quote: str,
    *,
    section: str | None = None,
    fragment_verified: bool = False,
) -> dict[str, object]:
    """보고서 출처 장부에 넣을 페이지 단위 위치 계약을 만든다."""
    quote = " ".join(quote.split())
    if not quote:
        raise ValueError("quote가 비어 있다")
    return {
        "source_url": source_url,
        "page": page,
        "section": section,
        "quote": quote,
        "page_url": page_deep_link(source_url, page, fragment_verified=fragment_verified),
        "page_fragment_verified": fragment_verified,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def highlight_pdf(
    input_path: Path,
    output_path: Path,
    marks: list[EvidenceMark],
    *,
    preview_dir: Path | None = None,
) -> dict[str, object]:
    """정확한 문구를 색상 표시한 새 PDF와 선택적 페이지 PNG를 생성한다."""
    input_path = input_path.resolve()
    output_path = output_path.resolve()
    if input_path == output_path:
        raise ValueError("원본 PDF를 덮어쓸 수 없다")
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    if output_path.exists():
        raise FileExistsError(f"기존 강조 사본을 덮어쓸 수 없다: {output_path}")
    if not marks:
        raise ValueError("강조할 근거가 없다")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if preview_dir is not None:
        preview_dir = preview_dir.resolve()
        if preview_dir.exists() and any(preview_dir.iterdir()):
            raise FileExistsError(f"미리보기 폴더가 비어 있지 않다: {preview_dir}")
        preview_dir.mkdir(parents=True, exist_ok=True)

    document = pymupdf.open(input_path)
    verified: list[tuple[EvidenceMark, str, list[pymupdf.Rect]]] = []
    temp_output = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        for mark in marks:
            if mark.page < 1 or mark.page > document.page_count:
                raise ValueError(
                    f"{mark.label}: page {mark.page}가 PDF 범위 1~{document.page_count} 밖이다"
                )
            if mark.color not in HIGHLIGHT_COLORS:
                raise ValueError(f"지원하지 않는 색상: {mark.color}")
            text = " ".join(mark.text.split())
            if not text:
                raise ValueError(f"{mark.label}: text가 비어 있다")

            page = document[mark.page - 1]
            rectangles = page.search_for(text)
            if not rectangles:
                raise EvidenceNotFoundError(
                    f"{mark.label}: {mark.page}쪽에서 지정 문구를 찾지 못했다"
                )
            verified.append((mark, text, rectangles))

        for mark, _text, rectangles in verified:
            page = document[mark.page - 1]
            annotation = page.add_highlight_annot(rectangles)
            annotation.set_colors(stroke=HIGHLIGHT_COLORS[mark.color])
            annotation.set_info(content=f"Kairos 근거 · {mark.label}")
            annotation.update()
        document.save(temp_output, garbage=4, deflate=True)
    finally:
        document.close()
    temp_output.replace(output_path)

    highlighted: list[HighlightedMark] = []
    with pymupdf.open(output_path) as rendered_document:
        output_page_count = rendered_document.page_count
        for mark, text, rectangles in verified:
            preview_path: str | None = None
            if preview_dir is not None:
                preview = preview_dir / f"page-{mark.page:04d}-{len(highlighted) + 1}.png"
                rendered_document[mark.page - 1].get_pixmap(
                    matrix=pymupdf.Matrix(1.6, 1.6),
                    alpha=False,
                ).save(preview)
                preview_path = str(preview)
            highlighted.append(
                HighlightedMark(
                    page=mark.page,
                    text=text,
                    label=mark.label,
                    color=mark.color,
                    matches=len(rectangles),
                    preview_path=preview_path,
                )
            )

    return {
        "input_path": str(input_path),
        "output_path": str(output_path),
        "input_sha256": _sha256(input_path),
        "output_sha256": _sha256(output_path),
        "page_count": output_page_count,
        "marks": [asdict(mark) for mark in highlighted],
        "original_preserved": True,
    }


def _parse_marks(path: Path) -> list[EvidenceMark]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_marks = payload.get("marks") if isinstance(payload, dict) else payload
    if not isinstance(raw_marks, list):
        raise ValueError("근거 JSON은 목록 또는 marks 목록을 포함한 객체여야 한다")
    return [EvidenceMark(**item) for item in raw_marks]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PDF 페이지 근거 강조 사본 생성")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--marks", required=True, type=Path)
    parser.add_argument("--preview-dir", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args(argv)

    manifest = highlight_pdf(
        args.input,
        args.output,
        _parse_marks(args.marks),
        preview_dir=args.preview_dir,
    )
    rendered = json.dumps(manifest, ensure_ascii=False, indent=2)
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
