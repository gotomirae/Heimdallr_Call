// PRD Ref: §9 — 용어 표시
//
// ★ 서버 컴포넌트다("use client" 없음). 툴팁을 native `title`로 내는 이유:
//   상태·이벤트가 필요 없고, 클라이언트 번들을 늘리지 않으며,
//   모바일에서 hover가 없어도 아래 `TermList`로 같은 내용을 읽을 수 있다.
// ★ 용어가 사전에 없으면 **점선을 그리지 않는다** — 설명이 있는 척하지 않는다.
import { GLOSSARY, GLOSSARY_SECTIONS, tooltip } from "@/lib/glossary";

/** 본문 안에서 용어에 밑줄과 툴팁을 붙인다. `term`을 생략하면 라벨을 키로 쓴다. */
export function Term({
  children,
  term,
}: {
  children: React.ReactNode;
  term?: string;
}) {
  const key = term ?? (typeof children === "string" ? children : "");
  const tip = tooltip(key);
  if (!tip) return <>{children}</>;
  return (
    <span
      title={tip}
      className="cursor-help border-b border-dotted border-slate-600 hover:border-slate-400"
    >
      {children}
    </span>
  );
}

// ★ Tailwind는 `text-${align}` 같은 **동적 클래스명을 생성하지 않는다.**
//   빌드도 타입 검사도 통과하고 스타일만 조용히 빠진다 — 반드시 전체 문자열로 쓴다.
const ALIGN_CLASS = {
  left: "text-left",
  right: "text-right",
  center: "text-center",
} as const;

/** 표 헤더용 — 굵기·색을 헤더에 맞춰 둔다. */
export function TermTh({
  children,
  term,
  align = "left",
}: {
  children: React.ReactNode;
  term?: string;
  align?: keyof typeof ALIGN_CLASS;
}) {
  const key = term ?? (typeof children === "string" ? children : "");
  const tip = tooltip(key);
  return (
    <th
      className={`px-3 py-2 font-medium ${ALIGN_CLASS[align]}`}
      title={tip}
      scope="col"
    >
      {tip ? (
        <span className="cursor-help border-b border-dotted border-slate-600">
          {children}
        </span>
      ) : (
        children
      )}
    </th>
  );
}

/** 용어 묶음을 펼쳐 보여준다. 툴팁을 못 쓰는 환경(모바일)의 실제 경로다. */
export function TermList({ terms }: { terms: string[] }) {
  return (
    <dl className="space-y-2">
      {terms.map((t) => {
        const def = GLOSSARY[t];
        if (!def) return null;
        return (
          <div key={t}>
            <dt className="text-sm font-semibold text-slate-200">{t}</dt>
            <dd className="text-sm text-slate-300">
              {def.short}
              {def.detail && (
                <span className="mt-0.5 block text-xs text-slate-400">{def.detail}</span>
              )}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

/** 전체 용어집. `/settings`와 상세화면 하단에서 함께 쓴다. */
export function Glossary({ sections = GLOSSARY_SECTIONS }: { sections?: typeof GLOSSARY_SECTIONS }) {
  return (
    <div className="grid gap-6 md:grid-cols-2">
      {sections.map((s) => (
        <section key={s.title}>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
            {s.title}
          </h3>
          <TermList terms={s.terms} />
        </section>
      ))}
    </div>
  );
}
