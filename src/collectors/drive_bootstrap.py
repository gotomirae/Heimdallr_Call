# PRD Ref: §8.7 G-4/G-5
"""Prepare local Google Drive sources immediately after claim, with a durable manifest."""
from __future__ import annotations

import calendar
from datetime import date, datetime
import json
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
import httpx
import yaml

from src.collectors.dart_disclosure import LIST_URL
from src.collectors.order_history_run import report_end
from src.collectors.sec_edgar import SecClient, archive_base, resolve_us, submissions
from src.config.constants import KAIROS_DOWNLOAD_INTERVAL_SECONDS, KAIROS_REPORT_COUNT, KAIROS_SOURCE_MONTHS
from src.notify.kairos_requests import normalize_drive_industry_folder
from src.universe.corp_code import fetch_corp_code_map
from src.utils.env import require_env

ROOT = Path(__file__).resolve().parents[2]
MAPPING = ROOT / 'config/industry_folders.yaml'
DRIVE_ROOT = Path('G:/내 드라이브/1. 주식 자본/2. 아이언맨의 투자 분석')


def safe_name(value: str) -> str:
    result = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip(' .')
    if not result or result in {'.', '..'} or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])', result):
        raise ValueError('INVALID_FILE_NAME')
    return result[:180]


def source_cutoff(today: date) -> date:
    index = today.year * 12 + today.month - 1 - KAIROS_SOURCE_MONTHS
    year, month0 = divmod(index, 12)
    month = month0 + 1
    return date(year, month, min(today.day, calendar.monthrange(year, month)[1]))


def source_date(path: Path) -> date | None:
    match = re.match(r'^(\d{6})_', path.name)
    if match:
        return datetime.strptime(match[1], '%y%m%d').date()
    # SC: Upload/sync modification time is not a publication date (ADR 21).
    return None


def recent_sources(folder: Path, today: date, ticker: str | None = None) -> list[Path]:
    files = list(folder.rglob('*')) if folder.exists() else []
    if ticker and folder.parent.exists():
        files += list(folder.parent.glob(f'??????_{ticker}.*'))
    return sorted((p for p in files if p.is_file() and p.suffix.lower() in {'.pdf', '.html', '.htm', '.pptx', '.docx', '.txt'}
                   and (published := source_date(p)) is not None
                   and source_cutoff(today) <= published <= today), key=source_date, reverse=True)


def mapped_folder(industry: str, sector: str = '') -> str | None:
    config = yaml.safe_load(MAPPING.read_text(encoding='utf-8'))
    key = normalize_drive_industry_folder(industry)
    matches = {v for k, v in config['folders'].items() if normalize_drive_industry_folder(k) == key}
    for k, overrides in config.get('overrides', {}).items():
        if normalize_drive_industry_folder(k) == key:
            found = {folder for token, folder in overrides.items() if token.casefold() in sector.casefold()}
            if len(found) > 1:
                raise ValueError('INDUSTRY_OVERRIDE_AMBIGUOUS')
            if found:
                return found.pop()
    if len(matches) > 1:
        raise ValueError('INDUSTRY_MAPPING_AMBIGUOUS')
    return next(iter(matches), None)


def industry_folder(industry: str, root: Path, today: date, sector: str = '') -> tuple[Path, bool]:
    # Lock protects number allocation AND YAML update across processes.
    lock = MAPPING.with_suffix('.lock')
    handle = lock.open('x', encoding='utf-8')
    try:
        mapped = mapped_folder(industry, sector)
        unmapped = mapped is None
        if not mapped:
            exact = [p.name for p in root.iterdir() if p.is_dir() and
                     normalize_drive_industry_folder(p.name) == normalize_drive_industry_folder(industry)]
            if len(exact) > 1:
                raise ValueError('INDUSTRY_FOLDER_AMBIGUOUS')
            if exact:
                mapped = exact[0]
            else:
                numbers = [int(m[1]) for p in root.iterdir() if p.is_dir()
                           and (m := re.match(r'^(\d+)\.', p.name))]
                mapped = f'{max(numbers, default=0) + 1}. {safe_name(industry)}'
        folder = root / safe_name(mapped)
        created = not folder.exists()
        folder.mkdir(exist_ok=True)
        if created:
            (folder / today.strftime('%y%m%d')).mkdir(exist_ok=True)
        config = yaml.safe_load(MAPPING.read_text(encoding='utf-8'))
        # Overrides must not overwrite the default mapping for all companies.
        if (not sector or unmapped) and config["folders"].get(industry) != mapped:
            config['folders'][industry] = mapped
            temporary = MAPPING.with_suffix('.tmp')
            temporary.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding='utf-8')
            temporary.replace(MAPPING)
        return folder, created
    finally:
        handle.close()
        lock.unlink(missing_ok=True)

class DartDownloads:
    def __init__(self):
        self.client = httpx.Client(timeout=90, follow_redirects=False, headers={"User-Agent": "Mozilla/5.0"})
        self.last = 0.0

    def get(self, url: str, **kwargs) -> httpx.Response:
        if urlparse(url).hostname not in {'dart.fss.or.kr', 'opendart.fss.or.kr'}:
            raise ValueError('DART_URL_NOT_ALLOWED')
        time.sleep(max(0, KAIROS_DOWNLOAD_INTERVAL_SECONDS - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        if "/pdf/download/pdf.do" in url or "/pdf/download/zip.do" in url:
            kwargs.setdefault("headers", {"Referer": url.replace("/pdf.do", "/main.do").replace("/zip.do", "/main.do")})
        response = self.client.get(url, **kwargs)
        response.raise_for_status()
        return response

    def listings(self, corp: str, today: date, category: str) -> list[dict]:
        result = []
        page = 1
        while True:
            body = self.get(LIST_URL, params={'crtfc_key': require_env('OPENDART_API_KEY'),
                'corp_code': corp, 'bgn_de': f'{today.year - 2}0101', 'end_de': today.strftime('%Y%m%d'),
                'pblntf_ty': category, 'page_count': 100, 'page_no': page}).json()
            if body.get('status') == '013':
                break
            if body.get('status') != '000':
                raise RuntimeError(f"DART_LIST_{body.get('status')}")
            result.extend(body.get('list', []))
            if page >= int(body['total_page']):
                break
            page += 1
        return sorted(result, key=lambda r: r['rcept_no'], reverse=True)

    def pdf_url(self, receipt: str) -> str:
        main = self.get('https://dart.fss.or.kr/dsaf001/main.do', params={'rcpNo': receipt})
        match = re.search(r'viewDoc\(\s*"(\d+)"\s*,\s*"(\d+)"', main.text)
        if not match or match[1] != receipt:
            raise ValueError('DART_DOCUMENT_ID_UNVERIFIED')
        page_url = f'https://dart.fss.or.kr/pdf/download/main.do?rcp_no={receipt}&dcm_no={match[2]}'
        page = self.get(page_url)
        links = BeautifulSoup(page.text, "html.parser").select('a[href]')
        expected = f'/pdf/download/pdf.do?rcp_no={receipt}&dcm_no={match[2]}'
        if not any(str(a["href"]) == expected for a in links):
            raise ValueError("DART_PDF_LINK_UNVERIFIED")
        return 'https://dart.fss.or.kr' + expected

    def ir_links(self, receipt: str) -> list[str]:
        main = self.get('https://dart.fss.or.kr/dsaf001/main.do', params={'rcpNo': receipt})
        pairs = re.findall(r"(?:openPdfDownload|pdfDownload)\(\s*['\"]?(\d+)['\"]?\s*,\s*['\"]?(\d+)['\"]?", main.text)
        if not pairs:
            match = re.search(r'viewDoc\(\s*"(\d+)"\s*,\s*"(\d+)"', main.text)
            pairs = [(match[1], match[2])] if match and match[1] == receipt else []
        main_soup = BeautifulSoup(main.text, "html.parser")
        for option in main_soup.select("#att option[value]"):
            query = parse_qs(str(option["value"]))
            rcp = query.get("rcpNo", [receipt])[0]
            dcm = query.get("dcmNo", [""])[0]
            if rcp == receipt and dcm.isdigit():
                pairs.append((rcp, dcm))
        links = []
        for rcp, dcm in set(pairs):
            if rcp != receipt:
                continue
            page = self.get('https://dart.fss.or.kr/pdf/download/main.do', params={'rcp_no': rcp, 'dcm_no': dcm})
            soup = BeautifulSoup(page.text, 'html.parser')
            # IR attachments only. The main IR announcement itself is not an IR deck.
            for tr in soup.select('tr'):
                for a in tr.select('a[href]'):
                    href = str(a['href'])
                    if re.search(r'\.pdf(?:$|[?&])', tr.get_text(' ', strip=True), re.I) and 'download' in href and '기업설명회' not in tr.get_text(' ', strip=True):
                        url = urljoin(str(page.url), href)
                        if urlparse(url).hostname == 'dart.fss.or.kr':
                            links.append(url)
        return sorted(set(links))


def save_download(client, url: str, destination: Path) -> dict:
    if destination.exists():
        return {'status': 'exists', 'file': str(destination), 'url': url}
    response = client.get(url)
    data = response.content
    if destination.suffix == '.pdf':
        if not data.startswith(b'%PDF-'):
            raise ValueError('DOWNLOAD_NOT_PDF')
        import fitz
        with fitz.open(stream=data, filetype='pdf') as document:
            if document.page_count == 0:
                raise ValueError('PDF_EMPTY')
    else:
        lower = data[:20000].lower()
        if b'<html' not in lower and b'<!doctype html' not in lower:
            raise ValueError('DOWNLOAD_NOT_HTML')
        if b'undeclared automated tool' in lower or b'request rate threshold' in lower:
            raise ValueError('SEC_ACCESS_BLOCKED')
    temporary = destination.with_suffix(destination.suffix + '.part')
    temporary.write_bytes(data)
    temporary.replace(destination)
    return {'status': 'downloaded', 'file': str(destination), 'url': url, 'bytes': len(data)}


def download_kr(job: dict, folder: Path, today: date) -> dict:
    client = DartDownloads()
    result = {'files': [], 'failures': [], 'ir': 'IR 자료 없음'}
    try:
        corp = fetch_corp_code_map().get(job['code'])
        if not corp:
            raise ValueError('DART_CORP_NOT_FOUND')
        periodic = client.listings(corp, today, 'A')
        seen = set()
        selected = []
        for row in periodic:
            end = report_end(row.get('report_nm'))
            if end and end not in seen and '[첨부정정]' not in row['report_nm']:
                seen.add(end)
                selected.append(row)
            if len(selected) == KAIROS_REPORT_COUNT:
                break
        for row in selected:
            try:
                name = f"{row['rcept_dt'][2:]}_{safe_name(job['company'])}_{safe_name(row['report_nm'])}.pdf"
                result['files'].append(save_download(client, client.pdf_url(row['rcept_no']), folder / name))
            except Exception as exc:
                result['failures'].append({'receipt': row['rcept_no'], 'source_url': f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={row['rcept_no']}", 'error': type(exc).__name__,
                    'reason': str(exc) if isinstance(exc, ValueError) else 'DOWNLOAD_FAILED'})
        try:
            ir = [r for r in client.listings(corp, today, 'I') if '기업설명회' in r.get('report_nm', '')]
            quarters = set()
            for row in ir:
                dt = datetime.strptime(row['rcept_dt'], '%Y%m%d').date()
                quarter = (dt.year, (dt.month - 1) // 3)
                if quarter in quarters:
                    continue
                try:
                    links = client.ir_links(row['rcept_no'])
                    if not links:
                        continue
                    quarters.add(quarter)
                    for index, url in enumerate(links):
                        name = f"{row['rcept_dt'][2:]}_{safe_name(job['company'])}_IR_{row['rcept_no']}_{index + 1}.pdf"
                        result['files'].append(save_download(client, url, folder / name))
                    result['ir'] = '공시 첨부 IR'
                except Exception as exc:
                    result['failures'].append({'receipt': row['rcept_no'], 'source_url': f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={row['rcept_no']}", 'error': type(exc).__name__})
                if len(quarters) == KAIROS_REPORT_COUNT:
                    break
        except Exception as exc:
            result['failures'].append({'source': 'IR 목록', 'error': type(exc).__name__})
        result['periodic_selected'] = len(selected)
        result['ir_quarters'] = len(quarters) if 'quarters' in locals() else 0
    finally:
        client.client.close()
    return result


def download_us(job: dict, folder: Path, today: date) -> dict:
    client = SecClient()
    result = {'files': [], 'failures': [], 'ir': 'IR 자료 없음'}
    try:
        company = resolve_us(job['ticker'])
        if not company:
            raise ValueError('SEC_TICKER_UNVERIFIED')
        body, rows = submissions(client, company['cik'])
        if job['ticker'] not in body.get('tickers', []):
            raise ValueError('SEC_SUBMISSIONS_TICKER_MISMATCH')
        seen = set()
        for row in rows:
            if row['form'] not in {'10-K', '10-Q'} or row['reportDate'] in seen:
                continue
            seen.add(row['reportDate'])
            try:
                base = archive_base(company['cik'], row['accessionNumber'])
                name = f"{row['filingDate'].replace('-', '')[2:]}_{safe_name(job['company'])}_{row['form']}_{row['accessionNumber']}.html"
                result['files'].append(save_download(client, base + row['primaryDocument'], folder / name))
            except Exception as exc:
                result['failures'].append({'accession': row['accessionNumber'], 'error': type(exc).__name__})
            if len(seen) == KAIROS_REPORT_COUNT:
                break
        quarters = set()
        for row in rows:
            if row['form'] != '8-K' or '2.02' not in row['items'].replace(' ', '').split(','):
                continue
            dt = date.fromisoformat(row['reportDate'] or row['filingDate'])
            key = (dt.year, (dt.month - 1) // 3)
            if key in quarters:
                continue
            quarters.add(key)
            try:
                base = archive_base(company['cik'], row['accessionNumber'])
                index = client.get(base + row['accessionNumber'] + '-index.html')
                soup = BeautifulSoup(index.text, 'html.parser')
                for tr in soup.select('tr'):
                    cells = [td.get_text(' ', strip=True) for td in tr.select('td')]
                    if not any(re.fullmatch(r'EX-99\.[12]', c, re.I) for c in cells):
                        continue
                    a = tr.select_one('a[href]')
                    if not a:
                        continue
                    url = urljoin(str(index.url), a['href'])
                    if not url.startswith(base):
                        raise ValueError('SEC_EXHIBIT_WRONG_ACCESSION')
                    ext = '.pdf' if urlparse(url).path.lower().endswith('.pdf') else '.html'
                    name = f"{row['filingDate'].replace('-', '')[2:]}_{safe_name(job['company'])}_IR_{row['accessionNumber']}_{safe_name(Path(urlparse(url).path).stem)}{ext}"
                    result['files'].append(save_download(client, url, folder / name))
                    result['ir'] = 'SEC EX-99 첨부'
            except Exception as exc:
                result['failures'].append({'accession': row['accessionNumber'], 'error': type(exc).__name__})
            if len(quarters) == KAIROS_REPORT_COUNT:
                break
        result['periodic_selected'] = len(seen)
        result['ir_quarters'] = len(quarters)
    finally:
        client.close()
    return result


def bootstrap(job: dict, *, root: Path = DRIVE_ROOT, today: date | None = None) -> dict:
    today = today or datetime.now(ZoneInfo('Asia/Seoul')).date()
    if not root.is_dir():
        raise RuntimeError('DRIVE_ROOT_UNAVAILABLE')
    if job['request_kind'] == 'industry':
        folder, created = industry_folder(job['target_name'], root / '1. 산업분석', today)
        children = [p for p in folder.iterdir() if p.is_dir() and re.fullmatch(r'\d{6}', p.name)]
        latest = max(children, key=lambda p: p.name) if children else folder
        return {'folder': str(folder), 'created': created, 'source_folder': str(latest),
                'files': [], 'failures': [], 'industry_pdf_destination': str(latest)}
    industry_result = {}
    if job.get("industry"):
        try:
            industry_path, industry_created = industry_folder(job["industry"], root / "1. 산업분석",
                                                               today, job.get("sector_hint", ""))
            children = [p for p in industry_path.iterdir() if p.is_dir() and re.fullmatch(r"\d{6}", p.name)]
            latest = max(children, key=lambda p: p.name) if children else industry_path
            industry_result = {"industry_folder": str(industry_path), "industry_created": industry_created,
                               "industry_pdf_destination": str(latest)}
        except Exception as exc:
            industry_result = {"industry_failure": type(exc).__name__}
    market = job.get('market', 'KR')
    folder = root / '2. 기업분석' / ('해외' if market == 'US' else '국내') / safe_name(
        job['ticker'] if market == 'US' else job['company'])
    recent = recent_sources(folder, today, job.get('ticker') if market == 'US' else None)
    if recent:
        return {'folder': str(folder), 'created': False, 'reused_sources': [str(p) for p in recent],
                'files': [], 'failures': [], **industry_result}
    created = not folder.exists()
    folder.mkdir(parents=True, exist_ok=True)
    try:
        result = (download_us if market == 'US' else download_kr)(job, folder, today)
    except Exception as exc:
        result = {"files": [], "failures": [{"source": market, "error": type(exc).__name__}],
                  "ir": "IR 자료 확인 실패"}

    return {'folder': str(folder), 'created': created, **industry_result, **result}
