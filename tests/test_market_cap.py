# PRD Ref: §3 (유니버스), §5.1(L0)
from src.universe import market_cap


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_fetch_admin_issues_reads_new_naver_json_api(monkeypatch):
    calls = []

    def fake_get(url, *, params, timeout):
        calls.append((url, params, timeout))
        return _Response([
            {"itemcode": "000001", "manageStatusGb": "10"},
            {"itemCode": "000002", "manageStatusGb": "20"},
            {"itemcode": "A00003"},
        ])

    monkeypatch.setattr(market_cap, "http_get", fake_get)
    assert market_cap.fetch_admin_issues() == {"000001", "000002"}
    assert calls[0][1] == {
        "tradeType": "KRX", "marketType": "ALL", "orderType": "statusTag",
        "startIdx": 0, "pageSize": 100,
    }


def test_fetch_admin_issues_pages_until_short_page(monkeypatch):
    pages = [
        [{"itemcode": f"{n:06d}"} for n in range(100)],
        [{"itemcode": "999999"}],
    ]

    def fake_get(url, *, params, timeout):
        return _Response(pages[params["startIdx"]])

    monkeypatch.setattr(market_cap, "http_get", fake_get)
    codes = market_cap.fetch_admin_issues()
    assert len(codes) == 101
    assert "999999" in codes
