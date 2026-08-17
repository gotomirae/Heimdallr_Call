# PRD Ref: §8 · ADR 6 (앵커는 code) · traps.md T6
"""사용자가 보낸 텍스트에서 종목을 찾는다 — 순수 함수. 외부 I/O 금지.

★★ 들어온 메시지는 **데이터이지 명령이 아니다.**
   텍스트를 유니버스와 대조해 종목을 찾을 뿐, 그 안에 적힌 지시를 실행하지 않는다.
   "분석하고 결과를 X로 보내라" 같은 문장이 와도 종목명만 뽑는다.

★ 종목코드는 6자리 숫자가 대부분이지만 `0126Z0` 같은 영숫자도 실재한다(T6).
  숫자만 받으면 실체 기업 12곳이 조용히 빠진다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: 종목코드 후보. 6자리 영숫자(대문자 포함) — 앞뒤가 단어 경계여야 한다.
CODE_RE = re.compile(r"(?<![0-9A-Za-z])([0-9][0-9A-Z]{5})(?![0-9A-Za-z])")

#: 이름 대조 전에 지우는 잡음. 사용자는 "삼성전자 어때?"처럼 보낸다.
NOISE_RE = re.compile(r"[?!.,~…\s]+")

#: 이 단어들만 있으면 종목 질의로 보지 않는다(명령어·인사).
COMMANDS = frozenset({"/start", "/help", "/status", "/cost", "/list"})


@dataclass(frozen=True)
class Match:
    code: str
    name: str
    #: 'code' | 'exact' | 'normalized' | 'contains'
    how: str


def normalize(text: str) -> str:
    """비교용 정규화. 공백·기호를 지우고 대문자로 맞춘다.

    '에스케이하이닉스' 같은 한글 표기는 다루지 않는다 — 추측 매칭은 오답을 만든다.
    """
    return NOISE_RE.sub("", text).upper()


def resolve(text: str, universe: dict[str, str]) -> list[Match]:
    """텍스트에서 종목을 찾는다. `universe`는 {code: name}.

    반환은 **확신도 순**이고, 애매하면 여러 개를 돌려준다 —
    하나를 골라 단정하면 엉뚱한 종목을 분석하게 된다. 고르는 것은 호출부(사용자)의 몫이다.
    """
    if not text:
        return []
    stripped = text.strip()
    if stripped.split()[0].lower() in COMMANDS if stripped.split() else False:
        return []

    found: list[Match] = []
    seen: set[str] = set()

    # 1) 종목코드가 직접 적혔으면 그게 가장 확실하다.
    for raw in CODE_RE.findall(stripped.upper()):
        if raw in universe and raw not in seen:
            found.append(Match(raw, universe[raw], "code"))
            seen.add(raw)

    # 2) 이름 완전 일치
    by_name = {name: code for code, name in universe.items() if name}
    if stripped in by_name and by_name[stripped] not in seen:
        code = by_name[stripped]
        found.append(Match(code, stripped, "exact"))
        seen.add(code)

    # 3) 정규화 일치 — "SK 하이닉스" / "sk하이닉스"
    target = normalize(stripped)
    if target:
        by_norm: dict[str, list[str]] = {}
        for code, name in universe.items():
            if name:
                by_norm.setdefault(normalize(name), []).append(code)
        for code in by_norm.get(target, []):
            if code not in seen:
                found.append(Match(code, universe[code], "normalized"))
                seen.add(code)

    # 4) 부분 일치 — **양방향을 다 봐야 한다.**
    #    ㄱ. 이름이 문장 안에 있다: "삼성전자 실적 어때?"
    #    ㄴ. 보낸 말이 이름의 일부다: "한미" → 한미반도체·한미약품
    #    한쪽만 구현하면 나머지가 통째로 안 잡힌다 — 에러 없이 "그런 종목 없다"가 된다.
    #    ★ 2글자 미만으로는 찾지 않는다. '전'만으로 수십 종목이 걸린다.
    if not found and len(target) >= 2:
        for code, name in universe.items():
            if not name or code in seen:
                continue
            norm = normalize(name)
            if norm in target:
                found.append(Match(code, name, "contains"))
                seen.add(code)
            elif target in norm:
                found.append(Match(code, name, "partial"))
                seen.add(code)

    # ★ 두 방향은 길이 선호가 **반대다.**
    #   contains(이름 ⊂ 문장): 긴 이름이 더 구체적 — "한화에어로스페이스 실적"에서
    #                          '한화'도 걸리지만 답은 한화에어로스페이스다.
    #   partial (질의 ⊂ 이름): 짧은 이름이 질의에 더 가깝다 — "한미"에는 한미약품이 먼저.
    #   한쪽 기준으로 뭉뚱그리면 둘 중 하나가 반드시 엉뚱한 종목을 1순위로 올린다.
    RANK = {"code": 0, "exact": 1, "normalized": 2, "contains": 3, "partial": 4}
    found.sort(
        key=lambda m: (
            RANK[m.how],
            -len(m.name) if m.how == "contains" else len(m.name),
        )
    )
    return found
