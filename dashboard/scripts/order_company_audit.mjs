// PRD Ref: §9.1-3 — 조사 장부도 운영 차트의 동일 순수 함수를 사용한다.
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import jitiPkg from "jiti";
const createJiti = jitiPkg.createJiti ?? jitiPkg;
const jiti = createJiti(fileURLToPath(import.meta.url), { interopDefault: true });
const { auditOrderCompany } = jiti(resolve(dirname(fileURLToPath(import.meta.url)), "../lib/orderCompany.ts"));
let input = "";
for await (const chunk of process.stdin) input += chunk;
const { universe, rows, generatedAt } = JSON.parse(input);
const grouped = new Map();
for (const row of rows) {
  const values = grouped.get(row.code) ?? [];
  values.push(row); grouped.set(row.code, values);
}
process.stdout.write(JSON.stringify(universe.map(company => auditOrderCompany(company, grouped.get(company.code) ?? [], generatedAt))));
