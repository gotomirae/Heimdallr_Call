# PRD Ref: §8.7 G-2/G-4/G-6
"""Service-only SEC registry and editable industry aliases; no Vault token reads."""
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo
import json

import yaml

from src.collectors.drive_bootstrap import MAPPING
from src.collectors.sec_edgar import SecClient, company_catalog, submissions
from src.config.constants import KAIROS_REGISTRY_BATCH_SIZE
from src.db.supabase_client import get_client, select_all
from src.notify.kairos_requests import normalize_drive_industry_folder


def refresh_us_company(ticker: str) -> dict:
    """Refresh reuse evidence even if Drive already has recent source files."""
    from src.collectors.sec_edgar import resolve_us
    company = resolve_us(ticker)
    if not company:
        raise ValueError("SEC_TICKER_UNVERIFIED")
    sec = SecClient()
    try:
        body, rows = submissions(sec, company["cik"])
        if ticker not in body.get("tickers", []):
            raise ValueError("SEC_SUBMISSIONS_TICKER_MISMATCH")
        earnings = [r["filingDate"] for r in rows if r["form"] in {"10-K", "10-Q"} or
                    (r["form"] == "8-K" and "2.02" in r["items"].replace(" ", "").split(","))]
        latest = datetime.combine(date.fromisoformat(max(earnings)), time.max, ZoneInfo("America/New_York")).isoformat() if earnings else None
        now = datetime.now(timezone.utc).isoformat()
        get_client().table("kairos_us_companies").upsert({
            **company, "verified_at": now, "latest_earnings_at": latest, "earnings_checked_at": now
        }).execute()
        return {"ticker": ticker, "earnings_checked_at": now, "latest_earnings_at": latest}
    finally:
        sec.close()


def sync_registry() -> dict:
    client = get_client()
    config = yaml.safe_load(MAPPING.read_text(encoding='utf-8'))
    aliases = {}
    for name, folder in config['folders'].items():
        key = normalize_drive_industry_folder(name)
        if key in aliases and aliases[key] != folder:
            raise ValueError('INDUSTRY_MAPPING_AMBIGUOUS')
        aliases[key] = folder
    client.table('kairos_industry_folders').upsert(
        [{'alias_key': k, 'folder_name': v} for k, v in aliases.items()]).execute()
    now = datetime.now(timezone.utc).isoformat()
    result = {'aliases': len(aliases), 'us_companies': 0, 'earnings_checked': 0, 'failures': []}
    sec = SecClient()
    try:
        companies = company_catalog(sec)
        for start in range(0, len(companies), KAIROS_REGISTRY_BATCH_SIZE):
            chunk = [{**r, 'verified_at': now} for r in companies[start:start + KAIROS_REGISTRY_BATCH_SIZE]]
            client.table('kairos_us_companies').upsert(chunk).execute()
            result['us_companies'] += len(chunk)
        requested = select_all('kairos_requests', 'ticker,status', filters={'market': 'US'}, order='update_id')
        wanted = {r['ticker'] for r in requested if r.get('ticker')}
        for company in companies:
            if company['ticker'] not in wanted:
                continue
            try:
                body, rows = submissions(sec, company['cik'])
                if company['ticker'] not in body.get('tickers', []):
                    raise ValueError('SEC_SUBMISSIONS_TICKER_MISMATCH')
                earnings = [r['filingDate'] for r in rows if
                            r['form'] in {'10-K', '10-Q'} or
                            (r['form'] == '8-K' and '2.02' in r['items'].replace(' ', '').split(','))]
                latest = datetime.combine(date.fromisoformat(max(earnings)), time.max, ZoneInfo('America/New_York')).isoformat() if earnings else None
                client.table('kairos_us_companies').update({'latest_earnings_at': latest,
                    'earnings_checked_at': now}).eq('ticker', company['ticker']).execute()
                result['earnings_checked'] += 1
            except Exception as exc:
                result['failures'].append({'ticker': company['ticker'], 'error': type(exc).__name__})
    finally:
        sec.close()
    return result


if __name__ == '__main__':
    print(json.dumps(sync_registry(), ensure_ascii=False))
