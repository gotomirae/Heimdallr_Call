# PRD Ref: §4.4 (매트릭스 등급 ★○△·)
"""Windows 콘솔 인코딩 방어.

Windows에서 stdout이 **파이프로 리다이렉트되면** Python이 콘솔 API 대신
로케일 인코딩(cp949)으로 떨어진다. 이 프로젝트는 등급 기호(★ ○ △ ·)와
표 괘선(═)을 출력하는데 cp949는 이들을 인코딩하지 못해

    UnicodeEncodeError: 'cp949' codec can't encode character '\\u2550'

로 **스크립트가 통째로 죽는다.** 터미널에서 직접 돌리면 멀쩡하고
`python -m ... | tee log.txt`나 GitHub Actions 로그 캡처에서만 죽어서
알아채기 어렵다.

출력하는 엔트리포인트마다 첫 줄에서 호출한다.
"""

from __future__ import annotations

import sys


def enable_utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        if (getattr(stream, "encoding", "") or "").lower().replace("-", "") == "utf8":
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # 재설정이 불가능한 스트림이면 조용히 포기한다.
            # 출력 인코딩 때문에 파이프라인을 죽이지는 않는다.
            pass
