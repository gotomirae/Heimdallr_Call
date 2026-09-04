// PRD Ref: §9.1 — 강조 렌더
//
// ★★ **중요한 키워드가 눈에 확 띄어야 한다**(사용자 지시 2026-08-23).
//   이 화면의 글은 길다. 평평한 회색 문단은 아무도 끝까지 읽지 않는다.
//
// ★ 규칙은 하나다: `**감싼 것**`은 굵게 + 색. 색은 **문맥이 정한다** —
//   가속이면 노랑(차트의 주인공 선과 같은 색), 둔화면 하늘색, 경고면 주황.
//   같은 강조 색을 아무 데나 쓰면 강조가 강조가 아니게 된다.
//
// ★ 서버 컴포넌트다("use client" 없음). 순수 렌더라 상태가 필요 없다.

/** 강조 색의 뜻. 여기 없는 색을 즉석에서 만들지 마라 — 화면마다 달라진다. */
export type EmphasisTone = "accel" | "flat" | "slow" | "unknown" | "warn" | "neutral";

const TONE_CLASS: Record<EmphasisTone, string> = {
  /** 가속·좋은 신호 — 차트의 영업이익 라인과 같은 노랑. */
  accel: "text-amber-200",
  /** 변화 없음. */
  flat: "text-slate-50",
  /** 둔화·주의 — 하락 색과 같은 하늘색. */
  slow: "text-sky-200",
  /** 판정 불가. */
  unknown: "text-slate-50",
  /** 경고 — 기저효과·확률 불일치처럼 "믿지 마라"는 신호. */
  warn: "text-orange-300",
  /** 색을 쓰지 않는 기본 강조. */
  neutral: "text-white",
};

/**
 * `**굵게**`를 실제 강조로 바꾼다.
 *
 * ★ 이걸 거치지 않고 문자열을 그대로 넣으면 **별표가 화면에 그대로 보인다.**
 *   실측(2026-08-22): 결과 추적의 인사이트 `action`이 그 상태였다.
 */
export default function Emphasized({
  text,
  tone = "neutral",
}: {
  text: string;
  tone?: EmphasisTone;
}) {
  return (
    <>
      {text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
        part.startsWith("**") && part.endsWith("**") ? (
          <strong key={i} className={`font-bold ${TONE_CLASS[tone]}`}>
            {part.slice(2, -2)}
          </strong>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </>
  );
}

/**
 * LLM이 쓴 **자유 서술**에서 눈에 걸려야 할 것들을 강조한다.
 *
 * ★★ 모델은 `**`를 쓰라고 시켜도 잘 안 쓴다. 그렇다고 아무 단어나 굵게 하면
 *   문단 전체가 굵어져 강조가 죽는다. 숫자·방향어와 함께 원인·전망·가치·가격을
 *   직접 판단하는 핵심 문장을 집는다.
 * ★ 문장 구조를 바꾸지 않는다. 원문은 그대로 두고 표시만 입힌다.
 */
export function Highlighted({ text }: { text: string }) {
  // 숫자 + 단위(%p·%·배·억·조·원·%p) 또는 방향을 가르는 낱말.
  const pattern =
    /([+-]?[\d,]+(?:\.\d+)?\s*(?:%p|%|배|억원|억|조원|조|원|개\s*분기|분기))|([^.!?。\n]*(?:핵심|원인|전망|지속|구조적|일시적|저평가|고평가|매력적|부담|아직 반영|이미 반영|가치|가격)[^.!?。\n]*(?:[.!?。]|$))|(급증|급감|급락|급등|확대|축소|개선|악화|둔화|가속|흑자전환|흑전|적자전환|적전|사상 최대|최고치|최저치)/g;

  const out: React.ReactNode[] = [];
  let cursor = 0;
  let m: RegExpExecArray | null;
  while ((m = pattern.exec(text)) !== null) {
    if (m.index > cursor) out.push(text.slice(cursor, m.index));
    out.push(
      <strong
        key={`${m.index}`}
        className="rounded bg-amber-300/15 px-0.5 font-semibold text-amber-200"
      >
        {m[0]}
      </strong>
    );
    cursor = m.index + m[0].length;
  }
  if (cursor < text.length) out.push(text.slice(cursor));
  return <>{out}</>;
}
