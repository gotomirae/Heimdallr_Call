"use client";
// PRD Ref: §9 — 페이지/가로/표 내부 스크롤에서도 항목과 정렬 제어 보존.
import { useEffect } from "react";
import { usePathname } from "next/navigation";

export default function TableHeaders() {
  const path = usePathname();
  useEffect(() => {
    const floating = document.createElement("div");
    floating.className = "table-header-float";
    floating.setAttribute("aria-hidden", "true");
    floating.hidden = true;
    document.body.appendChild(floating);
    let active: HTMLTableElement | null = null;
    let frame = 0;
    const draw = () => {
      frame = 0;
      const top = Math.max(0, document.querySelector("body > header")?.getBoundingClientRect().bottom ?? 0);
      const table = [...document.querySelectorAll<HTMLTableElement>("main table")].find(t => {
        const rect = t.getBoundingClientRect();
        const head = t.tHead?.getBoundingClientRect();
        return head && head.top < top && rect.bottom > top + head.height && rect.width > 0;
      });
      if (!table?.tHead) { floating.hidden = true; active = null; return; }
      const rect = table.getBoundingClientRect();
      let clip: HTMLElement = table.parentElement!;
      while (clip.parentElement && !/auto|scroll|hidden/.test(getComputedStyle(clip).overflowX)) clip = clip.parentElement;
      const bounds = clip.getBoundingClientRect();
      const left = Math.max(bounds.left, 0);
      floating.style.cssText = `top:${top}px;left:${left}px;width:${Math.min(bounds.right, innerWidth) - left}px;`;
      const copy = document.createElement("table");
      copy.className = table.className;
      copy.style.width = `${rect.width}px`;
      const head = table.tHead.cloneNode(true) as HTMLTableSectionElement;
      head.querySelectorAll("[id]").forEach(n => n.removeAttribute("id"));
      head.querySelectorAll<HTMLElement>("button,input,a,select").forEach(n => n.tabIndex = -1);
      const original = [...table.tHead.querySelectorAll("th")];
      head.querySelectorAll<HTMLElement>("th").forEach((cell, i) => {
        const width = original[i].getBoundingClientRect().width;
        cell.style.width = `${width}px`; cell.style.minWidth = `${width}px`; cell.style.maxWidth = `${width}px`;
      });
      copy.appendChild(head);
      floating.replaceChildren(copy);
      floating.scrollLeft = clip.scrollLeft + left - bounds.left;
      floating.hidden = false;
      active = table;
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(draw); };
    const onScroll = (event: Event) => { if (event.target !== floating) schedule(); };
    const click = (event: MouseEvent) => {
      const target = event.target as HTMLElement;
      const cell = target.closest("th");
      if (!cell || !active?.tHead) return;
      const i = [...floating.querySelectorAll("th")].indexOf(cell);
      const original = active.tHead.querySelectorAll<HTMLElement>("th")[i];
      const control = target.closest("button,input,a,select");
      const similar = control ? original.querySelector<HTMLElement>(control.tagName.toLowerCase()) : null;
      (similar ?? original).click();
      schedule();
    };
    floating.addEventListener("click", click);
    document.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", schedule);
    const observer = new MutationObserver(schedule);
    const main = document.querySelector("main");
    if (main) observer.observe(main, { childList: true, subtree: true, characterData: true });
    schedule();
    return () => { cancelAnimationFrame(frame); observer.disconnect(); floating.remove();
      document.removeEventListener("scroll", onScroll, true); window.removeEventListener("resize", schedule); };
  }, [path]);
  return null;
}
