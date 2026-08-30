// 종목 상세 수주 신호의 순수 변환을 Python 회귀 테스트에서 실제 실행한다.
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import jitiPkg from "jiti";

const here = dirname(fileURLToPath(import.meta.url));
const createJiti = jitiPkg.createJiti ?? jitiPkg;
const jiti = createJiti(fileURLToPath(import.meta.url), { interopDefault: true });
const { deriveOrderDisclosureSignal } = jiti(resolve(here, "..", "lib", "orderSignals.ts"));

const input = await new Promise((done) => {
  let buf = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk) => (buf += chunk));
  process.stdin.on("end", () => done(buf));
});

const cases = JSON.parse(input);
process.stdout.write(JSON.stringify(cases.map((c) => deriveOrderDisclosureSignal(c.row, c.year, c.quarter))));
