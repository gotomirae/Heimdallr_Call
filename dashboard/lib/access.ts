// PRD Ref: §9 — 대시보드 접근 제한 (사용자 지시 2026-08-23)
//
// ★★ **허용 이메일을 코드에 적지 마라.**
//   이 저장소는 **공개(public)**다. 명단을 커밋하면 13명의 이메일 주소가
//   인터넷에 그대로 공개된다 — 접근을 막으려다 개인정보를 뿌리는 셈이다.
//   그래서 명단은 **환경변수**로만 받는다(`DASHBOARD_ALLOWED_EMAILS`).
//
// ★ 서버에서만 읽는다. `NEXT_PUBLIC_` 접두사를 붙이면 **브라우저 번들에 박혀**
//   누구나 명단을 볼 수 있다 — 접두사를 붙이지 않는 것이 이 파일의 핵심이다.
//
// ★ 목록이 비어 있으면 **아무도 통과시키지 않는다**(fail-closed).
//   설정을 빠뜨렸을 때 "전원 허용"으로 열리면 제한이 있으나 마나다.

/** 이메일 비교는 **소문자·공백 제거** 후에 한다. 대소문자가 다르면 조용히 막힌다. */
function normalize(email: string): string {
  return email.trim().toLowerCase();
}

/**
 * 허용된 이메일 목록. 쉼표 또는 줄바꿈으로 구분한다.
 *
 * ★ 환경변수가 없으면 **빈 배열**이다 — 그리고 빈 배열이면 전원 차단이다.
 */
export function allowedEmails(): string[] {
  const raw = process.env.DASHBOARD_ALLOWED_EMAILS ?? "";
  return [
    ...new Set(
      raw
        .split(/[,\n;]/)
        .map(normalize)
        .filter((v) => v.includes("@"))
    ),
  ];
}

/**
 * 이 이메일이 대시보드를 볼 수 있는가.
 *
 * ★★ **fail-closed.** 명단이 비었거나 이메일이 없으면 `false`다.
 *   "설정이 없으면 일단 열어 둔다"는 편의는 접근 제한을 무력화한다.
 */
export function isAllowed(email: string | null | undefined): boolean {
  if (!email) return false;
  const list = allowedEmails();
  if (list.length === 0) return false;
  return list.includes(normalize(email));
}

/** 명단이 설정돼 있는가 — 화면에 "설정이 빠졌다"를 알리기 위해 쓴다. */
export function isConfigured(): boolean {
  return allowedEmails().length > 0;
}
