// 섹터 분류 **구현 대조용** — 파이썬 테스트(`tests/test_sector_map_parity.py`)가 실행한다.
//
// ★ 왜 필요한가: 규칙 데이터는 `constants.json`으로 한 곳에서 오지만
//   **알고리즘은 파이썬과 TS에 따로 적혀 있다**(위치 우선 · 제외어 · 업종전용).
//   한쪽만 고치면 같은 종목이 화면과 DB에서 다른 섹터로 보이는데 **에러는 안 난다.**
//   그래서 실제 값을 넣어 두 구현의 출력을 글자까지 대조한다.
//
// 사용법: stdin으로 [[industry, products], ...] JSON을 받아 결과 배열을 stdout에 낸다.
import { readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import jitiPkg from "jiti"; // CommonJS — 네임드 임포트는 노드에서 깨진다

const here = dirname(fileURLToPath(import.meta.url));
const libDir = resolve(here, "..", "lib");

// ★ `sector.ts`는 Next 규약대로 '@/lib/constants.json'을 임포트한다. jiti의 별칭
//   옵션은 이 버전에서 조용히 안 먹었다(실측) — 그래서 **소스를 그대로 읽어**
//   그 한 줄만 상대경로로 바꿔 임시 파일로 돌린다. 알고리즘은 손대지 않는다.
const source = readFileSync(join(libDir, "sector.ts"), "utf8").replace(
  /["']@\/lib\/constants\.json["']/g,
  JSON.stringify("./constants.json")
);

const shim = join(libDir, `.sector-parity-${process.pid}.ts`);
writeFileSync(shim, source, "utf8");

let classifySector;
try {
  const createJiti = jitiPkg.createJiti ?? jitiPkg;
  const jiti = createJiti(fileURLToPath(import.meta.url), { interopDefault: true });
  ({ classifySector } = jiti(shim));
} finally {
  rmSync(shim, { force: true });
}

const input = await new Promise((done) => {
  let buf = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (c) => (buf += c));
  process.stdin.on("end", () => done(buf));
});

const cases = JSON.parse(input);
process.stdout.write(
  JSON.stringify(cases.map(([industry, products]) => classifySector(industry, products)))
);
