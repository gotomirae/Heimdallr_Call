"use client";
// PRD Ref: §9 — 등급·섹터 복수 선택 (사용자 요청 2026-08-22)
//
// ★ `<select multiple>`을 쓰지 않는다. 브라우저 기본 다중 선택은 Ctrl/Cmd를 눌러야
//   하고, 그걸 모르면 **클릭할 때마다 앞 선택이 지워진다** — 기능이 있는데 없는 것처럼
//   보이는 가장 나쁜 형태다. 체크박스 목록으로 만들어 클릭이 곧 토글이 되게 한다.
import { useEffect, useRef, useState } from "react";

export interface Option {
  value: string;
  /** 화면에 보일 이름. 없으면 value를 그대로 쓴다. */
  label?: string;
  /** 오른쪽에 붙는 개수 등. */
  hint?: string;
  /** 색을 입혀야 하는 항목(등급 기호). */
  color?: string;
}

export default function MultiSelect({
  label,
  options,
  selected,
  onChange,
  widthClass = "w-44",
}: {
  /** 아무것도 안 골랐을 때 버튼에 뜨는 이름. 그대로 "전체"의 뜻이다. */
  label: string;
  options: Option[];
  selected: string[];
  onChange: (next: string[]) => void;
  widthClass?: string;
}) {
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  // 바깥을 누르면 닫는다. 안 닫으면 표를 가린 채로 남아 스크롤을 막는다.
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function toggle(value: string) {
    onChange(
      selected.includes(value)
        ? selected.filter((v) => v !== value)
        : [...selected, value]
    );
  }

  // ★ 버튼 글자가 선택 내용을 그대로 말해야 한다. "3개 선택"이라고만 쓰면
  //   무엇을 골랐는지 보려고 매번 열어봐야 한다.
  const summary =
    selected.length === 0
      ? `${label} 전체`
      : selected.length <= 2
        ? selected.join(" · ")
        : `${selected.slice(0, 2).join(" · ")} 외 ${selected.length - 2}`;

  return (
    <div ref={boxRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={`${label} 선택`}
        className={`flex ${widthClass} items-center justify-between gap-1 rounded border px-2 py-1 text-left text-sm ${
          selected.length > 0
            ? "border-amber-500/70 bg-amber-950/30 text-amber-100"
            : "border-slate-600 bg-slate-900 text-slate-100"
        }`}
      >
        <span className="truncate">{summary}</span>
        <span className="shrink-0 text-xs text-slate-300">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="absolute left-0 z-40 mt-1 max-h-72 w-64 overflow-auto rounded border border-slate-600 bg-slate-900 p-1 shadow-xl">
          <div className="flex items-center justify-between px-2 py-1 text-xs text-slate-300">
            <span>{selected.length === 0 ? "전체 표시 중" : `${selected.length}개 선택`}</span>
            {selected.length > 0 && (
              <button
                type="button"
                onClick={() => onChange([])}
                className="text-sky-300 hover:underline"
              >
                모두 해제
              </button>
            )}
          </div>
          {options.map((o) => {
            const on = selected.includes(o.value);
            return (
              <label
                key={o.value}
                className={`flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-sm hover:bg-slate-800 ${
                  on ? "bg-slate-800/70" : ""
                }`}
              >
                <input
                  type="checkbox"
                  checked={on}
                  onChange={() => toggle(o.value)}
                  className="h-3.5 w-3.5 accent-amber-500"
                />
                <span
                  className="flex-1 truncate text-slate-100"
                  style={o.color ? { color: o.color, fontWeight: 700 } : undefined}
                >
                  {o.label ?? o.value}
                </span>
                {o.hint && <span className="shrink-0 text-xs text-slate-300">{o.hint}</span>}
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}
