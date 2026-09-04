// PRD Ref: §9 /settings — 임계값 · 비용 현황
//
// ★ 임계값은 **읽기 전용**이다. 여기서 고칠 수 있게 만들면 화면과 파이썬 상수가
//   갈라지고, 어느 쪽이 실제로 쓰이는지 아무도 모르게 된다.
//   `src/config/constants.py`가 유일한 출처이고 이 화면은 그걸 비춰 보일 뿐이다.
import { headers } from "next/headers";
import { Glossary } from "@/components/Term";
import constants from "@/lib/constants.json";
import { selectAll } from "@/lib/supabase";
import type { CostSummary } from "@/app/api/cost/route";

export const dynamic = "force-dynamic";

interface NotificationRow {
  id: number;
  kind: string | null;
  sent_at: string | null;
  // ★★ 억제분(`--suppress`)은 **보내지 않았는데도** 중복 차단을 위해 같은 표에 남는다.
  //   payload의 표식을 안 보면 "발송 78건"으로 조용히 거짓말한다.
  payload: { suppressed?: boolean; reason?: string } | null;
}

function Card({ title, note, children }: {
  title: string; note?: string; children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <h2 className="mb-1 text-sm font-semibold text-slate-100">{title}</h2>
      {note && <p className="mb-3 text-xs text-slate-300">{note}</p>}
      {children}
    </section>
  );
}

function Row({ label, value, hint }: {
  label: string; value: string; hint?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-slate-800/60 py-1.5 last:border-b-0">
      <span className="text-sm text-slate-100">
        {label}
        {hint && <span className="ml-2 text-xs text-slate-300">{hint}</span>}
      </span>
      <span className="shrink-0 font-mono text-sm tabular-nums text-slate-100">{value}</span>
    </div>
  );
}

export default async function SettingsPage() {
  // ★ 비용은 **서버사이드 라우트를 경유**한다. `cost_log`에 anon 정책이 없어
  //   클라이언트에서 바로 읽으면 RLS가 빈 배열을 줘 "$0"으로 잘못 보인다.
  const host = headers().get("host") ?? "localhost:3000";
  const proto = host.startsWith("localhost") ? "http" : "https";
  const [cost, notifications] = await Promise.all([
    fetch(`${proto}://${host}/api/cost`, { cache: "no-store" })
      .then((r) => r.json() as Promise<CostSummary>)
      .catch(() => null),
    selectAll<NotificationRow>("notifications", "id,kind,sent_at,payload"),
  ]);

  const ceiling = constants.cost.monthly_ceiling_usd;
  const spent = cost?.spentUsd ?? 0;
  const usedPct = ceiling > 0 ? (spent / ceiling) * 100 : 0;
  const monthKey = cost?.monthKey ?? "";

  // ★ 실제 발송과 억제를 **갈라서** 센다. 합쳐 세면 보내지도 않은 건이
  //   발송 건수로 잡힌다 — 화면은 멀쩡하고 숫자만 틀린다.
  const byKind = new Map<string, number>();
  const suppressedByKind = new Map<string, number>();
  for (const n of notifications) {
    const k = n.kind ?? "기타";
    const target = n.payload?.suppressed ? suppressedByKind : byKind;
    target.set(k, (target.get(k) ?? 0) + 1);
  }
  const suppressedTotal = [...suppressedByKind.values()].reduce((a, b) => a + b, 0);
  const suppressedReason = notifications.find((n) => n.payload?.suppressed)?.payload?.reason;

  const axes = constants.score_axes as Record<string, number>;
  const items = constants.score_items as Record<string, number>;
  const pri = constants.pri as Record<string, number>;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold">설정 · 비용</h1>
        <p className="mt-1 text-sm text-slate-200">
          임계값은 <strong>읽기 전용</strong>이다 — 고치려면{" "}
          <code className="rounded bg-slate-800 px-1 text-xs">src/config/constants.py</code>를
          수정하고 <code className="rounded bg-slate-800 px-1 text-xs">
            python -m src.config.export_constants
          </code>를 돌린다.
        </p>
        <p className="mt-1 text-xs text-slate-300">
          화면에서 고칠 수 있게 만들면 파이썬 상수와 갈라져
          <strong> 어느 쪽이 실제로 쓰이는지 알 수 없게 된다.</strong>
        </p>
      </div>

      <Card
        title="LLM 비용"
        note={`이번 달(${monthKey}) 실호출 기준. 실링에 닿으면 호출을 멈추고 다음 달로 이월한다.`}
      >
        {!cost?.available && (
          <p className="mb-3 rounded border border-amber-800/60 bg-amber-900/20 px-3 py-2 text-xs text-amber-300">
            ⚠ 비용을 읽지 못했다 — {cost?.reason ?? "서버 응답 없음"}
            <br />
            아래 숫자를 <strong>&ldquo;비용 0&rdquo;으로 읽지 마라.</strong>
          </p>
        )}
        <div className="space-y-3">
          <div className="flex items-baseline gap-3">
            <span className="text-3xl font-bold tabular-nums">
              {cost?.available ? `$${spent.toFixed(4)}` : "—"}
            </span>
            <span className="text-sm text-slate-200">/ ${ceiling}</span>
            {cost?.available && (
              <span className="text-sm text-slate-300">({usedPct.toFixed(1)}%)</span>
            )}
          </div>
          <div className="h-3 overflow-hidden rounded bg-slate-800">
            <div
              className={usedPct >= 80 ? "h-full bg-amber-500" : "h-full bg-emerald-600"}
              style={{ width: `${Math.min(usedPct, 100)}%` }}
            />
          </div>
          <div className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
            <Row
              label="이번 달 호출"
              value={cost?.available ? `${cost.monthCalls}건` : "—"}
            />
            <Row
              label="누적 호출(prod)"
              value={cost?.available ? `${cost.totalCalls}건` : "—"}
            />
            <Row label="모델" value={String(constants.cost.model)} />
            <Row
              label="단가"
              value={`$${constants.cost.input_per_mtok}/$${constants.cost.output_per_mtok} per Mtok`}
            />
            <Row
              label="입력 토큰 예산"
              value={`${Number(constants.cost.input_token_budget).toLocaleString("ko-KR")}`}
              hint="초과 시 호출 안 함"
            />
          </div>
          <div className="mt-4 rounded border border-sky-800/70 bg-sky-950/30 p-3">
            <p className="text-xs text-sky-200">다음 달({cost?.nextMonthKey ?? "—"}) 예측</p>
            <p className="mt-1 text-2xl font-bold tabular-nums text-white">
              {cost?.available && cost.nextMonthForecastUsd != null
                ? `$${cost.nextMonthForecastUsd.toFixed(4)}`
                : "—"}
            </p>
            <p className="mt-1 text-xs text-slate-300">
              {cost?.forecastBasis ?? "예측할 실호출 이력이 없다."}
              {" · 실제 배치 규모에 따라 달라질 수 있다."}
            </p>
          </div>

          <div className="mt-4">
            <h3 className="mb-2 text-xs font-semibold text-slate-200">월별 실호출 비용 · 최근 12개월</h3>
            {cost?.available && cost.months.length > 0 ? (
              <div className="overflow-hidden rounded border border-slate-800">
                {cost.months.map((item) => (
                  <div key={item.monthKey}
                       className="grid grid-cols-3 border-b border-slate-800/70 px-3 py-2 text-sm last:border-b-0">
                    <span className="text-slate-200">{item.monthKey}</span>
                    <span className="text-right font-mono tabular-nums text-white">
                      ${item.spentUsd.toFixed(4)}
                    </span>
                    <span className="text-right text-slate-300">{item.calls}건</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-slate-300">월별 비용 기록이 없다.</p>
            )}
          </div>
        </div>
      </Card>

      <Card title="발송 이력" note="같은 (종목, 분기, 종류)는 두 번 나가지 않는다.">
        {notifications.length === 0 ? (
          <p className="text-sm text-slate-300">발송 기록이 없다.</p>
        ) : (
          <div className="grid gap-x-6 sm:grid-cols-2">
            {[...byKind.entries()].map(([kind, n]) => (
              <Row key={kind} label={kind} value={`${n}건`} />
            ))}
          </div>
        )}
      </Card>

      {suppressedTotal > 0 && (
        <Card
          title="발송 억제"
          note="발굴은 됐지만 알림을 보내지 않은 건. 대시보드에는 그대로 나온다 — 중복 차단 표에만 미리 채워 두었다."
        >
          <div className="grid gap-x-6 sm:grid-cols-2">
            {[...suppressedByKind.entries()].map(([kind, n]) => (
              <Row key={kind} label={kind} value={`${n}건`} />
            ))}
          </div>
          {suppressedReason && (
            <p className="mt-3 text-xs text-slate-400">사유: {suppressedReason}</p>
          )}
        </Card>
      )}

      <Card
        title="스코어 배점"
        note="합계 100점. 미측정 축은 0점이 아니라 분모에서 빠진다(ADR 2) — 컨센서스가 없는 종목이 구조적으로 불리해지지 않게 하는 장치다."
      >
        <div className="grid gap-x-8 sm:grid-cols-2">
          <div>
            {Object.entries(axes).map(([key, value]) => (
              <Row key={key} label={key.replace("_", " ")} value={`${value}점`} />
            ))}
            <Row label="합계" value={`${Object.values(axes).reduce((a, b) => a + b, 0)}점`} />
          </div>
          <div>
            {Object.entries(constants.denominators as Record<string, number>).map(
              ([key, value]) => (
                <Row
                  key={key}
                  label={
                    key
                      .replace("flash", "즉시")
                      .replace("final", "확정")
                      .replace("_with_consensus", " · 컨센 있음")
                      .replace("_no_consensus", " · 컨센 없음")
                  }
                  value={`분모 ${value}`}
                />
              )
            )}
          </div>
        </div>
        <details className="mt-3">
          <summary className="cursor-pointer text-xs text-slate-300 hover:text-slate-100">
            항목별 배점 14개 보기
          </summary>
          <div className="mt-2 grid gap-x-8 sm:grid-cols-2">
            {Object.entries(items).map(([key, value]) => (
              <Row key={key} label={key} value={`${value}점`} />
            ))}
          </div>
        </details>
      </Card>

      <Card
        title="주가반영도 (PRI)"
        note="낮을수록 실적이 아직 주가에 덜 반영된 상태다. 분모 하한 미만이면 0점이 아니라 '판정 불가'다."
      >
        <div className="grid gap-x-8 sm:grid-cols-2">
          <div>
            <Row label="P1 52주 신고가 대비" value={`${pri.p1}점`} />
            <Row label="P2 발표 당일 종가 대비" value={`${pri.p2}점`} />
            <Row label="P3 과거 9분기 평균 PER 대비" value={`${pri.p3}점`} />
            <Row label="P4 발표 후 5거래일 외국인 수급" value={`${pri.p4}점`} />
            <Row label="P5 RSI 45 기준" value={`${pri.p5}점`} />
          </div>
          <div>
            <Row label="분모 하한" value={`${pri.min_denominator}`} hint="미만이면 판정 보류" />
            <Row
              label="미반영 / 선반영 경계"
              value={`${constants.matrix.pri_low} / ${constants.matrix.pri_high}`}
            />
          </div>
        </div>
      </Card>

      <Card title="성장 가속 · 매트릭스 · 발송">
        <div className="grid gap-x-8 sm:grid-cols-2">
          <div>
            <Row
              label="시가총액 하한"
              value={`${(Number(constants.gate.market_cap_floor_krw) / 1e8).toLocaleString("ko-KR")}억`}
            />
            <Row
              label="최소 분기 이력"
              value={`${constants.gate.min_quarters_history}분기`}
              hint="미만이면 신규 상장"
            />
            <Row
              label="데이터 시작"
              value={`${constants.data.start_year}.${constants.data.start_quarter}Q`}
            />
          </div>
          <div>
            <Row label="고스코어 기준" value={`${constants.matrix.score_high}점`} />
            <Row label="중스코어 기준" value={`${constants.matrix.score_mid}점`} />
            <Row
              label="컨센서스 인정"
              value={`추정 ${constants.consensus.min_estimates}곳 이상`}
            />
            <Row
              label="발송 등급"
              value={(constants.notify.grades as string[]).join(" ")}
              hint={`하루 최대 ${constants.notify.daily_max}건`}
            />
          </div>
        </div>
      </Card>

      {/* ★ 용어집 — 화면 곳곳의 툴팁과 **같은 출처**(`lib/glossary.ts`)를 쓴다.
          설명을 화면마다 따로 쓰면 조용히 어긋난다. */}
      <Card
        title="용어"
        note="이 시스템이 쓰는 낱말이 각각 무엇을 재는지. 표 머리글에 마우스를 올려도 같은 설명이 뜬다."
      >
        <div className="rounded border border-slate-800 bg-slate-950/40 p-3 text-sm text-slate-100">
          <strong className="text-slate-100">성장 가속</strong> — 매출 YoY 가속 + 영업이익
          YoY 가속 + OPM YoY 상승을 <strong>모두</strong> 만족한 것.
          <div className="mt-2 font-mono text-xs leading-relaxed text-slate-200">
            G1 매출{"   "}revenue_yoy(t) &gt; revenue_yoy(t−1){"  "}AND{"  "}revenue_yoy(t) &gt; 0
            <br />
            G2 영업익 op_yoy(t){"     "}&gt; op_yoy(t−1){"      "}AND{"  "}op_yoy(t){"     "}&gt; 0
            <br />
            G4 OPM{"      "}opm(t) &gt; opm(t−4)
          </div>
          <p className="mt-2 text-xs text-slate-300">
            전년 적자에서 당기 흑자로 돌아선 &lsquo;흑전&rsquo;은 성장률(%)을 계산할 수 없지만
            별도 <strong>턴어라운드</strong> 유형으로 분류한다. 전분기 성장률을 모르면 탈락이
            아니라 <strong>판정 불가</strong>다 — 결측을 탈락으로 뭉개면 데이터가 덜 모인
            소형주가 통째로 사라지는데, 이 시스템의 발굴 대상이 정확히 그 구간이다.
          </p>
        </div>
        <div className="mt-4">
          <Glossary />
        </div>
      </Card>
    </div>
  );
}
