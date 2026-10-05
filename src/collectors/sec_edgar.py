# PRD Ref: §8.7 G-5/G-6
"""SEC identity cache and explicit filing selection; no LLM or trading APIs."""
from __future__ import annotations

import json
from pathlib import Path
import re
import time
from urllib.parse import urlparse

import httpx
import yaml

from src.config.constants import KAIROS_DOWNLOAD_INTERVAL_SECONDS, KAIROS_SEC_CACHE_SECONDS
from src.utils.env import require_env

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / '.cache' / 'sec_tickers.json'


class SecClient:
    def __init__(self):
        agent = require_env('SEC_USER_AGENT')
        if not re.search(r'[^\s@()]+@[^\s@()]+\.[^\s@()]+', agent):
            raise ValueError('SEC_USER_AGENT_CONTACT_REQUIRED')
        self.client = httpx.Client(headers={'User-Agent': agent}, timeout=60, follow_redirects=False)
        self.last_call = 0.0

    def get(self, url: str) -> httpx.Response:
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname not in {'www.sec.gov', 'data.sec.gov'}:
            raise ValueError('SEC_URL_NOT_ALLOWED')
        time.sleep(max(0, KAIROS_DOWNLOAD_INTERVAL_SECONDS - (time.monotonic() - self.last_call)))
        self.last_call = time.monotonic()
        response = self.client.get(url)
        response.raise_for_status()
        return response

    def close(self):
        self.client.close()


def company_catalog(client: SecClient | None = None) -> list[dict]:
    if CACHE.exists() and time.time() - CACHE.stat().st_mtime < KAIROS_SEC_CACHE_SECONDS:
        return json.loads(CACHE.read_text(encoding='utf-8'))
    own = client is None
    client = client or SecClient()
    try:
        ticker_body = client.get('https://www.sec.gov/files/company_tickers.json').json()
        ticker_rows = {r['ticker'].upper(): r for r in ticker_body.values()}
        body = client.get('https://www.sec.gov/files/company_tickers_exchange.json').json()
        rows = [dict(zip(body['fields'], values, strict=True)) for values in body['data']]
        catalog = [{'ticker': r['ticker'].upper(), 'name': ticker_rows[r['ticker'].upper()]['title'],
                    'cik': str(r['cik']).zfill(10), 'exchange': r['exchange']} for r in rows
                   if r.get('exchange') in {'Nasdaq', 'NYSE'} and r['ticker'].upper() in ticker_rows
                   and int(r['cik']) == int(ticker_rows[r['ticker'].upper()]['cik_str'])]
        if not catalog or len({r['ticker'] for r in catalog}) != len(catalog):
            raise ValueError('SEC_CATALOG_INVALID')
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        temporary = CACHE.with_suffix('.tmp')
        temporary.write_text(json.dumps(catalog, ensure_ascii=False), encoding='utf-8')
        temporary.replace(CACHE)
        return catalog
    finally:
        if own:
            client.close()


def resolve_us(text: str, catalog: list[dict] | None = None) -> dict | None:
    text = text.strip()
    if not text or len(text) > 200 or '\n' in text:
        return None
    aliases = yaml.safe_load((ROOT / 'config/us_company_aliases.yaml').read_text(encoding='utf-8'))['aliases']
    lookup = str(aliases.get(text, text)).upper()
    rows = catalog if catalog is not None else company_catalog()
    matches = [r for r in rows if lookup in {r['ticker'].upper(), r['name'].upper()}]
    return matches[0] if len(matches) == 1 else None


def filing_rows(columns: dict) -> list[dict]:
    """Parallel SEC arrays must have identical lengths; never zip-truncate."""
    keys = ('form', 'filingDate', 'accessionNumber', 'primaryDocument', 'reportDate', 'items')
    count = len(columns.get('form', []))
    if any(len(columns.get(k, [])) != count for k in keys[:4]) or any(
        k in columns and len(columns[k]) != count for k in keys[4:]
    ):
        raise ValueError('SEC_ARRAY_LENGTH_MISMATCH')
    return [{k: columns.get(k, [''] * count)[i] for k in keys} for i in range(count)]


def submissions(client: SecClient, cik: str) -> tuple[dict, list[dict]]:
    body = client.get(f'https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json').json()
    rows = filing_rows(body['filings']['recent'])
    from src.config.constants import KAIROS_REPORT_COUNT
    # One year/1,000 records can exclude quarterly reports for very active filers.
    for page in body['filings'].get('files', []):
        if len({r['reportDate'] for r in rows if r['form'] in {'10-K', '10-Q'}}) >= KAIROS_REPORT_COUNT and len(
            {r['reportDate'] or r['filingDate'] for r in rows if r['form'] == '8-K' and '2.02' in r['items']}
        ) >= KAIROS_REPORT_COUNT:
            break
        name = page['name']
        if not re.fullmatch(r'CIK\d+-submissions-\d+\.json', name):
            raise ValueError('SEC_HISTORY_NAME_INVALID')
        rows.extend(filing_rows(client.get(f'https://data.sec.gov/submissions/{name}').json()))
    return body, sorted(rows, key=lambda r: (r['filingDate'], r['accessionNumber']), reverse=True)


def archive_base(cik: str, accession: str) -> str:
    if not re.fullmatch(r'\d{10}-\d{2}-\d{6}', accession):
        raise ValueError('SEC_ACCESSION_INVALID')
    return f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace("-", "")}/'
