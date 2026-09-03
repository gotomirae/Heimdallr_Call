// PRD Ref: §9 — 관심 종목
import { DiscoveryPage } from "@/app/page";

export const dynamic = "force-dynamic";

export default async function WatchlistPage() {
  return <DiscoveryPage watchlistOnly />;
}
