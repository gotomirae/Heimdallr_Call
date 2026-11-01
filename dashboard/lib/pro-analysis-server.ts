// PRD Ref: §7/9 · ADR50 — queue only, no models on Vercel.
import { createHmac, timingSafeEqual } from "node:crypto";
import { createClient } from "@supabase/supabase-js";
import { NextRequest } from "next/server";
import { NO_STORE_OPTIONS } from "@/lib/supabase";
export function analysisAdmin() {
  const url = (process.env.SUPABASE_URL ?? process.env.NEXT_PUBLIC_SUPABASE_URL)?.trim();
  const key = process.env.SUPABASE_SERVICE_KEY?.trim();
  return url && key ? createClient(url, key, NO_STORE_OPTIONS) : null;
}
export function analysisAuthorized(request: NextRequest): boolean {
  const serviceKey = process.env.SUPABASE_SERVICE_KEY?.trim();
  const secret = process.env.ANALYSIS_ACCESS_TOKEN?.trim() || (serviceKey
    ? createHmac("sha256", serviceKey).update("heimdallr-owner-analysis-v1").digest("hex") : undefined);
  const provided = request.headers.get("authorization")?.replace(/^Bearer /, "").trim();
  if (!secret || !provided) return false;
  const a = Buffer.from(secret), b = Buffer.from(provided);
  return a.length === b.length && timingSafeEqual(a, b);
}
export function analysisKey(kind: string, target: string, year?: number, quarter?: number) {
  return `${kind}:${target}:${year ?? ""}:${quarter ?? ""}`;
}
