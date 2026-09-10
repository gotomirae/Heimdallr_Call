import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // 등급 색상 — 화면 전체에서 이 다섯 개만 쓴다.
        grade: {
          star: "#f59e0b",     // ★ 기업 고점수·미반영
          circle: "#10b981",   // ○
          triangle: "#6366f1", // △ 기업 고점수·선반영
          dot: "#64748b",      // ·
          cross: "#ef4444",    // ✕ 기업 저점수·선반영
        },
      },
    },
  },
  plugins: [],
};
export default config;
