// 종목 상세 수주 신호의 순수 변환을 Python 회귀 테스트에서 실제 실행한다.
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import jitiPkg from "jiti";

const here = dirname(fileURLToPath(import.meta.url));
const createJiti = jitiPkg.createJiti ?? jitiPkg;
const jiti = createJiti(fileURLToPath(import.meta.url), { interopDefault: true });
const { postPeriodContracts, reportNamePeriodEnd, currentQuarterPostReportContracts, deriveOrderDisclosureSignal, extractOrderContractDisclosure, extractOrderDisclosureMetric, isAttachmentOnlyCorrection, summarizeOrderDisclosure } = jiti(resolve(here, "..", "lib", "orderSignals.ts"));
const { quarterlyCharacteristics } = jiti(resolve(here, "..", "lib", "metricMeaning.ts"));
const { withOrderBacklogQoq, attachOrderReportPoints } = jiti(resolve(here, "..", "lib", "chart.ts"));

const input = await new Promise((done) => {
  let buf = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk) => (buf += chunk));
  process.stdin.on("end", () => done(buf));
});

const cases = JSON.parse(input);
process.stdout.write(JSON.stringify(cases.map((c) => c.quarterStudy
  ? quarterlyCharacteristics(c.points)
  : c.periodWindow ? postPeriodContracts(c.rows, c.basisDate, c.periodEnd)
  : c.periodName ? reportNamePeriodEnd(c.reportName)
  : c.attachmentCorrection
  ? isAttachmentOnlyCorrection(c.reportName)
  : c.orderReportPoints
  ? withOrderBacklogQoq(attachOrderReportPoints(c.points, c.reports))
  : c.contractWindow
  ? currentQuarterPostReportContracts(c.rows, c.basisDate, c.latestPeriodicReportDate)
  : c.chartQoq
  ? withOrderBacklogQoq(c.points)
  : c.contract
  ? extractOrderContractDisclosure(c.row)
  : c.summary
  ? summarizeOrderDisclosure(c.row)
  : c.metric ? extractOrderDisclosureMetric(c.row)
  : deriveOrderDisclosureSignal(c.row, c.year, c.quarter))));
