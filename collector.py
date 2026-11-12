"""One-click daily rate collector for the standalone procurement dashboard.

The four provider pages are opened in a real browser (Playwright). Only each page's
displayed default date is collected; that date is stored as observed, without a local
holiday calendar or guessed target date. Ambiguous targets are recorded as failures.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import time
import argparse
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data.json"
HTML_PATH = ROOT / "index.html"
BACKUP_DIR = ROOT / "backups"
RETENTION_DAYS = 30

PROVIDERS = [
    {"id": "nice", "name": "나이스", "url": "https://www.nicepni.com/data/ytm", "kind": "nice"},
    {"id": "kap", "name": "한국", "url": "https://www.koreaap.com/kor/valuation01_01.html", "kind": "kap"},
    {"id": "kis", "name": "KIS", "url": "https://www.bond.co.kr/conts/10075#none;", "kind": "kis"},
    {"id": "fn", "name": "에프앤", "url": "https://www.fnpricing.com/fr/pc/profit/ytm", "kind": "fn"},
]
PRODUCT_FIN = "financial_aa_minus_3y"
PRODUCT_GOV = "government_3y"


def kst_now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Seoul"))


def normalize_date(raw: str) -> str:
    match = re.search(r"(20\d{2})[.\-/년 ]+([01]?\d)[.\-/월 ]+([0-3]?\d)", raw or "")
    if not match:
        raise ValueError(f"화면 기준일 식별 실패: {raw!r}")
    year, month, day = map(int, match.groups())
    return datetime(year, month, day).date().isoformat()


def numeric_rate(raw: str) -> int:
    value = (raw or "").strip().replace(",", "")
    if not re.fullmatch(r"\d{1,2}\.\d{3}", value):
        raise ValueError(f"금리 숫자/정밀도 확인필요: {raw!r}")
    return int(round(float(value) * 1000))


def check_access(page) -> None:
    body = page.locator("body").inner_text(timeout=20000)
    blocked = ["captcha", "access denied", "403 forbidden", "접근이 차단", "로그인 후 이용"]
    if any(term in body.lower() for term in blocked):
        raise ValueError("접근 제한 또는 로그인 요구가 화면에 표시됨")


def date_from_input(page, selector: str | None = None) -> str:
    if selector:
        el = page.locator(selector)
        if el.count() != 1:
            raise ValueError(f"기준일 입력란 식별 실패: {selector}")
        value = el.evaluate("el => el.value") or el.get_attribute("value") or ""
        return normalize_date(value)
    fields = page.locator("input").evaluate_all(
        "els => els.map(e => ({value:e.value, type:e.type, id:e.id, name:e.name}))"
    )
    candidates = []
    for field in fields:
        try:
            candidates.append(normalize_date(str(field.get("value", ""))))
        except (ValueError, TypeError):
            continue
    candidates = sorted(set(candidates))
    if len(candidates) != 1:
        raise ValueError(f"화면의 기준일을 하나로 확인할 수 없음: {candidates}")
    return candidates[0]


def table_rows(page):
    return page.locator("table, [role='table'], [role='grid'], [role='treegrid']").evaluate_all(
        "tables => tables.map(t => [...t.querySelectorAll('tr,[role=row]')].map(r => "
        "[...r.querySelectorAll('th,td,[role=cell],[role=columnheader]')].map(c => (c.innerText||'').trim())))"
    )


def find_header(rows, predicate) -> int:
    matches = []
    for i, row in enumerate(rows):
        if any(predicate(cell) for cell in row):
            matches.append(i)
    if len(matches) != 1:
        raise ValueError(f"3년/3Y 열 머리글이 하나로 식별되지 않음 ({len(matches)}건)")
    return next(j for j, cell in enumerate(rows[matches[0]]) if predicate(cell))


def parse_nice(page):
    date = date_from_input(page)
    headers = page.locator(".ag-header-cell-text").all_inner_texts()
    cols = [i for i, cell in enumerate(headers) if re.fullmatch(r"\s*3Y\s*", cell, re.I)]
    if len(cols) != 1:
        raise ValueError(f"나이스 YTM 3Y 열을 유일하게 찾지 못함 ({len(cols)}건)")
    col = cols[0]
    rows = page.locator(".ag-row").evaluate_all(
        "els => els.map(r => [...r.querySelectorAll('.ag-cell')].map(c => (c.innerText||'').trim()))"
    )
    candidates = {PRODUCT_FIN: [], PRODUCT_GOV: []}
    for row in rows:
        cells = [re.sub(r"\s+", " ", c).strip() for c in row]
        if len(cells) > col and len(cells) >= 3 and cells[0] == "여전채" and cells[1] == "AA-":
            candidates[PRODUCT_FIN].append((cells[col], "여전채 / AA- / 3Y"))
        if len(cells) > col and len(cells) >= 3 and cells[0] == "국고채" and re.search(r"양곡.*외평", cells[1]):
            candidates[PRODUCT_GOV].append((cells[col], "국고채 / 양곡·외평 / 3Y"))
    return date, resolve_values(candidates)


def parse_fn(page):
    date = date_from_input(page, "#profitSearchDate")
    tables = table_rows(page)
    candidates = {PRODUCT_FIN: [], PRODUCT_GOV: []}
    for rows in tables:
        header = next((r for r in rows if any(re.fullmatch(r"\s*3Y\s*", c, re.I) for c in r)), None)
        if not header:
            continue
        col = next(i for i, c in enumerate(header) if re.fullmatch(r"\s*3Y\s*", c, re.I))
        in_financial_ii = False
        expect_financial_aa_minus = False
        for row in rows:
            if len(row) <= col:
                if row and row[0] == "금융채(II)":
                    in_financial_ii = True
                continue
            cells = [re.sub(r"\s+", " ", c).strip() for c in row]
            if cells[0] == "금융채(II)":
                in_financial_ii = True
            if in_financial_ii and len(cells) >= 3 and cells[0:3] == ["금융채(II)", "금융기관", "AA+"]:
                expect_financial_aa_minus = True
                continue
            if expect_financial_aa_minus:
                if len(cells) >= 2 and cells[0] == "AA-":
                    offset = max(0, len(header) - len(cells))
                    value_col = col - offset
                    if 0 <= value_col < len(cells):
                        candidates[PRODUCT_FIN].append((cells[value_col], "금융채(II) / 금융기관 / AA- / 3Y"))
                    expect_financial_aa_minus = False
                elif cells[0] not in {"AAA", "AA+", "AA", "A+", "A", "A-", "BBB+", "BBB", "BBB-"}:
                    expect_financial_aa_minus = False
            if len(cells) >= 3 and cells[0] == "국채" and cells[1] == "국고":
                candidates[PRODUCT_GOV].append((cells[col], "국채 / 국고 / 3Y"))
    return date, resolve_values(candidates)


def parse_kis(page):
    date = date_from_input(page, "#datepickerBefore")
    tables = table_rows(page)
    candidates = {PRODUCT_FIN: [], PRODUCT_GOV: []}
    for rows in tables:
        header = next((r for r in rows if any(re.fullmatch(r"\s*3Y\s*", c, re.I) for c in r)), None)
        if not header:
            continue
        col = next(i for i, c in enumerate(header) if re.fullmatch(r"\s*3Y\s*", c, re.I))
        in_financial_ii = False
        in_other_financial = False
        for row in rows:
            cells = [re.sub(r"\s+", " ", c).strip() for c in row]
            if "금융채Ⅱ" in cells:
                in_financial_ii = True
                in_other_financial = False
            if in_financial_ii and "기타금융채" in cells:
                in_other_financial = True
            if in_financial_ii and in_other_financial and "금융AA-" in cells:
                offset = max(0, len(header) - len(cells))
                value_col = col - offset
                if 0 <= value_col < len(cells):
                    candidates[PRODUCT_FIN].append((cells[value_col], "금융채Ⅱ / 기타금융채 / 금융AA- / 3Y"))
            if len(cells) >= 4 and cells[0] == "국채" and cells[1] == "국고채권" and cells[2] == "국고채":
                if len(cells) > col:
                    candidates[PRODUCT_GOV].append((cells[col], "국채 / 국고채권 / 국고채 / 3Y"))
    return date, resolve_values(candidates)


def parse_kap(page):
    date = date_from_input(page, "#txtStdDateY")
    selector = page.locator("#cmbSearchTypeY")
    if selector.count() != 1:
        raise ValueError("조회구분을 확인할 수 없음")
    current = selector.locator("option:checked").inner_text().strip()
    if current != "기준 수익률":
        raise ValueError(f"조회구분이 기준 수익률이 아님: {current}")
    labels_table = page.locator("table#tbl_val.table_2:visible")
    rates_table = page.locator("table#tbl_val:visible:not(.table_2)")
    if labels_table.count() != 1 or rates_table.count() != 1:
        raise ValueError(f"보이는 분류표/금리표를 유일하게 찾지 못함 (분류 {labels_table.count()}개, 금리 {rates_table.count()}개)")
    labels, rates = [
        table.locator("tr").evaluate_all(
            "rs => rs.map(r => [...r.querySelectorAll('th,td')].map(c => (c.innerText||'').trim()))"
        )
        for table in [labels_table, rates_table]
    ]
    if len(labels) != len(rates) or not labels or not rates:
        raise ValueError("분류표와 금리표 행 수가 일치하지 않음")
    header = rates[0]
    cols = [i for i, cell in enumerate(header) if re.fullmatch(r"\s*3년\s*", cell)]
    if len(cols) != 1:
        raise ValueError("3년 만기 열을 하나로 식별하지 못함")
    col = cols[0]
    financial, government = [], []
    current_group = current_class = ""
    for i in range(1, len(labels)):
        row = [re.sub(r"\s+", " ", x).strip() for x in labels[i]]
        rating = ""
        if len(row) >= 4:
            current_group, current_class, rating = row[0], row[1], row[2]
        elif len(row) == 3:
            # The first cell is a child classification under a vertically merged group cell.
            if current_group == "금융채 II":
                current_class, rating = row[0], row[1]
            elif current_group == "국채":
                current_class, rating = row[0], row[1]
            else:
                rating = row[0]
        elif len(row) == 2:
            rating = row[0]
        if current_group == "국채" and current_class == "국고채" and re.search(r"국고.*양곡.*외평.*재정", " ".join(row)):
            government.append(i)
        if current_group == "금융채 II" and current_class == "기타금융" and rating == "AA-":
            financial.append(i)
    def value_at(index):
        if index >= len(rates) or col >= len(rates[index]):
            raise ValueError("분류표·금리표 행 대응이 범위를 벗어남")
        return rates[index][col]
    candidates = {
        PRODUCT_FIN: [(value_at(i), "금융채 II / 기타금융 / AA- / 3년") for i in financial],
        PRODUCT_GOV: [(value_at(i), "국채 / 국고채 / 국고·양곡·외평·재정 / 3년") for i in government],
    }
    return date, resolve_values(candidates)


def resolve_values(candidates):
    result, errors = {}, {}
    for product, found in candidates.items():
        if len(found) != 1:
            errors[product] = f"대상 행이 하나가 아님 ({len(found)}건)"
            continue
        raw, item = found[0]
        try:
            result[product] = {"rateMilli": numeric_rate(raw), "item": item}
        except ValueError as exc:
            errors[product] = str(exc)
    return result, errors


PARSERS = {"nice": parse_nice, "kap": parse_kap, "kis": parse_kis, "fn": parse_fn}


def backup_files(now: datetime) -> None:
    BACKUP_DIR.mkdir(exist_ok=True)
    tag = now.strftime("%Y%m%d_%H%M%S")
    for path in (DATA_PATH, HTML_PATH):
        if path.exists():
            shutil.copy2(path, BACKUP_DIR / f"{path.stem}_{tag}{path.suffix}")
    cutoff = now.timestamp() - RETENTION_DAYS * 86400
    for path in BACKUP_DIR.iterdir():
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink()


def atomic_text(path: Path, text: str) -> None:
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(text, encoding="utf-8", newline="\n")
    temp.replace(path)


def update_embedded_html(db: dict) -> None:
    html = HTML_PATH.read_text(encoding="utf-8")
    payload = json.dumps(
        {"records": db.get("records", []), "issues": db.get("issues", []), "runs": db.get("runs", [])},
        ensure_ascii=False, separators=(",", ":"),
    ).replace("</", "<\\/")
    pattern = re.compile(r'(<script id="embedded" type="application/json">).*?(</script>)', re.S)
    updated, count = pattern.subn(lambda m: m.group(1) + payload + m.group(2), html, count=1)
    if count != 1:
        raise ValueError("HTML에 데이터 삽입 위치가 하나로 확인되지 않음")
    atomic_text(HTML_PATH, updated)


def add_if_missing(db: dict, provider: dict, date: str, values: dict, collected_at: str) -> list[str]:
    added = []
    for product, item in values.items():
        index = next((i for i, r in enumerate(db.get("records", []))
                      if r.get("date") == date and r.get("provider") == provider["id"] and r.get("product") == product), None)
        if index is not None and db["records"][index].get("status") == "normal":
            continue
        record = {
            "date": date, "provider": provider["id"], "product": product,
            "rateMilli": item["rateMilli"], "status": "normal", "source": provider["url"],
            "collectedAt": collected_at, "item": item["item"], "origin": "web",
        }
        if index is None:
            db.setdefault("records", []).append(record)
        else:
            db["records"][index] = record
        added.append(product)
    return added


def set_check_required(db: dict, provider: dict, date: str, product: str, reason: str, collected_at: str) -> None:
    record = {
        "date": date, "provider": provider["id"], "product": product, "rateMilli": None,
        "status": "check_required", "source": provider["url"], "collectedAt": collected_at,
        "item": "", "error": reason, "origin": "web",
    }
    index = next((i for i, r in enumerate(db.get("records", []))
                  if r.get("date") == date and r.get("provider") == provider["id"] and r.get("product") == product), None)
    if index is None:
        db.setdefault("records", []).append(record)
    else:
        db["records"][index] = record


def collect_latest(db: dict, now: datetime) -> tuple[dict, dict]:
    db.setdefault("records", []); db.setdefault("issues", []); db.setdefault("runs", [])
    collected_at = now.isoformat(timespec="seconds")
    run = {"startedAt": collected_at, "providers": [], "status": "partial"}
    try:
        with sync_playwright() as playwright:
            launch_options = {"headless": True}
            if os.environ.get("PROCUREMENT_USE_BUNDLED_CHROMIUM") != "1":
                launch_options["channel"] = "chrome"
            browser = playwright.chromium.launch(**launch_options)
            try:
                for provider in PROVIDERS:
                    result = {"provider": provider["id"], "name": provider["name"], "status": "check_required", "added": []}
                    page = browser.new_page(locale="ko-KR", timezone_id="Asia/Seoul")
                    page.set_default_timeout(25000)
                    try:
                        page.goto(provider["url"], wait_until="domcontentloaded", timeout=45000)
                        page.wait_for_function(
                            "() => /(?:^|\\s)(?:3Y|3년)(?:\\s|$)/m.test(document.body.innerText)",
                            timeout=30000,
                        )
                        if provider["kind"] == "nice":
                            page.wait_for_function("() => document.querySelectorAll('.ag-row').length > 5", timeout=30000)
                        elif provider["kind"] == "kap":
                            page.wait_for_function("() => document.querySelectorAll('table.table_2 tr').length > 10 && document.querySelectorAll('table#tbl_val tr').length > 10", timeout=30000)
                        page.wait_for_timeout(1000)
                        check_access(page)
                        date, (values, errors) = PARSERS[provider["kind"]](page)
                        if date > now.date().isoformat():
                            raise ValueError(f"화면 기준일이 미래 날짜임: {date}")
                        result["date"] = date
                        result["added"] = add_if_missing(db, provider, date, values, collected_at)
                        for product, reason in errors.items():
                            set_check_required(db, provider, date, product, reason, collected_at)
                        result["status"] = "check_required" if errors and not values else "partial" if errors else "normal" if result["added"] else "already_present"
                        result["items"] = list(values.keys())
                        result["errors"] = errors
                        print(f"{provider['name']}: {date} 확인, 신규 {len(result['added'])}건", file=sys.stderr)
                    except Exception as exc:
                        result["error"] = str(exc)[:500]
                        print(f"{provider['name']}: 확인필요 - {result['error']}", file=sys.stderr)
                    finally:
                        page.close()
                    run["providers"].append(result)
                    time.sleep(1)
            finally:
                browser.close()
        run["status"] = "normal" if all(p["status"] in ("normal", "already_present") for p in run["providers"]) else "partial"
    except Exception as exc:
        run["status"] = "failed"
        run["error"] = str(exc)[:500]
        print(f"수집 실행 실패: {run['error']}", file=sys.stderr)
    run["finishedAt"] = kst_now().isoformat(timespec="seconds")
    db["runs"].append(run)
    db["runs"] = db["runs"][-180:]
    return db, run


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="JSON stdin을 입력으로 받아 파일을 저장하지 않고 결과 JSON을 stdout으로 반환")
    args = parser.parse_args()
    if args.demo:
        try:
            initial = json.load(sys.stdin)
            updated, run = collect_latest(initial, kst_now())
            json.dump({"db": updated, "run": run}, sys.stdout, ensure_ascii=False, separators=(",", ":"))
            sys.stdout.write("\n")
            return 0
        except Exception as exc:
            print(f"시연 수집 실행 실패: {exc}", file=sys.stderr)
            return 1
    if not DATA_PATH.exists() or not HTML_PATH.exists():
        print("필요한 data.json 또는 index.html이 없습니다.")
        return 2
    db = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    now = kst_now()
    backup_files(now)
    db, run = collect_latest(db, now)
    atomic_text(DATA_PATH, json.dumps(db, ensure_ascii=False, indent=2) + "\n")
    update_embedded_html(db)
    print(f"DB 및 HTML 갱신 완료. 수집 상태: {run['status']}")
    return 0 if run["status"] in ("normal", "partial") else 1


if __name__ == "__main__":
    sys.exit(main())
