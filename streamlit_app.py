from __future__ import annotations

import calendar
import html
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from decimal import Decimal, ROUND_HALF_UP
from psycopg.types.json import Jsonb
import plotly.graph_objects as go
import streamlit as st

from collector import collect_latest, kst_now

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data.json"
BACKUP_DIR = ROOT / "backups"
KST = ZoneInfo("Asia/Seoul")
PROVIDER_NAMES = {"nice": "나이스", "kap": "한국", "kis": "KIS", "fn": "에프앤"}
PROVIDER_ORDER = ["nice", "kap", "kis", "fn"]
PROVIDER_COLORS = {"nice": "#2557c7", "kap": "#15805d", "kis": "#d78317", "fn": "#8649ad"}
PROVIDER_URLS = {
    "nice": "https://www.nicepni.com/data/ytm",
    "kap": "https://www.koreaap.com/kor/valuation01_01.html",
    "kis": "https://www.bond.co.kr/conts/10075#none",
    "fn": "https://www.fnpricing.com/fr/pc/profit/ytm",
}
PRODUCTS = {
    "financial_aa_minus_3y": "금융채 II AA- 3년물",
    "government_3y": "국고채 3년물",
}
PRODUCT_OPTIONS = {"금융채": "financial_aa_minus_3y", "국채": "government_3y", "금융채 + 국채 동시 조회": "both"}
CALENDAR_EVENTS = [
    {"date": "2026-11-03", "area": "한국 · 물가", "title": "10월 소비자물가 동향", "time": "08:00 KST", "url": "https://www.kostat.go.kr/boardDownload.es?bid=5146&list_no=443886&seq=3", "class": "kr"},
    {"date": "2026-11-06", "area": "미국 · 고용", "title": "10월 고용보고서", "time": "08:30 ET", "url": "https://www.bls.gov/schedule/2026/", "class": "us"},
    {"date": "2026-11-10", "area": "미국 · CPI", "title": "10월 소비자물가지수", "time": "08:30 ET", "url": "https://www.bls.gov/schedule/2026/", "class": "us"},
    {"date": "2026-11-10", "area": "일본 · BOJ", "title": "10/29–30 회의 의견 요약", "time": "08:50 JST", "url": "https://www.boj.or.jp/en/about/calendar/index.htm", "class": "jp"},
    {"date": "2026-11-13", "area": "미국 · PPI", "title": "10월 생산자물가지수", "time": "08:30 ET", "url": "https://www.bls.gov/schedule/2026/", "class": "us"},
    {"date": "2026-11-17", "area": "미국 · 무역물가", "title": "10월 수출입물가지수", "time": "08:30 ET", "url": "https://www.bls.gov/schedule/2026/", "class": "us"},
    {"date": "2026-11-18", "area": "미국 · FOMC", "title": "10/27–28 회의 의사록", "time": "14:00 ET", "url": "https://www.federalreserve.gov/newsevents/2026-november.htm", "class": "us"},
    {"date": "2026-11-26", "area": "한국 · 금융통화위원회", "title": "통화정책방향 회의", "time": "한국은행 공식 일정", "url": "https://www.bok.or.kr/portal/singl/mainEvent/listCldr.do?menuNo=200035", "class": "kr"},
]
PREVIOUS_MONTH_NEWS = [
    {"id": "oct15-riskoff", "date": "2026-10-15", "title": "AI주 급락 뒤 안전자산 선호, 국고채 금리 하락", "summary": "국내 주식 급락과 위험회피 속에 국고채 3년 금리는 1.6bp 하락한 3.867%로 마감했다. 보도는 국내외 국채로의 안전자산 수요를 함께 다뤘다.", "sources": [("Aju Press", "https://m.ajupress.com/view/20261015164953008")]},
    {"id": "oct22-bok", "date": "2026-10-22", "title": "한국은행 기준금리 3.00% 동결, 성장·물가 경계 유지", "summary": "금통위는 기준금리를 동결했다. 한국은행은 수출·투자 호조와 높은 물가, 금융안정 위험을 언급했고, 시장 보도는 성장 전망과 향후 인상 가능성에 주목했다.", "sources": [("한국은행 결정문", "https://www.bok.or.kr/eng/bbs/E0000634/view.do?menuNo=400069&nttId=11065825"), ("Reuters 보도", "https://www.marketscreener.com/news/bank-of-korea-holds-rates-upbeat-outlook-points-to-future-hikes-ce785cd9df88f525")]},
    {"id": "oct28-fed", "date": "2026-10-28", "title": "FOMC 금리 동결, 물가 경계와 장기금리 변동", "summary": "연준은 정책금리 목표범위를 3.75~4.00%로 유지하고 물가가 여전히 높다고 평가했다. Reuters는 회의 뒤 미 국채 장기물 금리 움직임을 보도했다.", "sources": [("연준 성명", "https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm"), ("Reuters 보도", "https://www.marketscreener.com/news/fomc-holds-rates-steady-markets-mostly-follow-suit-ce785cd2d080f521")]},
    {"id": "oct30-boj", "date": "2026-10-30", "title": "BOJ 금리 동결, 물가 전망 상향과 추가 인상 신호", "summary": "일본은행은 단기 정책금리를 유지하면서 물가 전망을 상향하고 정책 정상화 여지를 남겼다. Reuters는 엔화와 미 국채금리 움직임을 함께 전했다.", "sources": [("BOJ 정책문", "https://www.boj.or.jp/en/mopo/mpmdeci/mpr_2026/k261030a.pdf"), ("Reuters 보도", "https://www.marketscreener.com/news/yen-gains-after-boj-ai-jitters-drive-treasury-rally-weigh-on-dollar-ce785fdad08ff725")]},
]

st.set_page_config(page_title="조달금리 조회 페이지", page_icon="📈", layout="wide")
st.markdown("""
<style>
.block-container{max-width:1500px;padding-top:1rem}.topbar{background:#10233f;color:#fff;padding:1rem 1.4rem;border-radius:12px;margin-bottom:1rem}.topbar h1{font-size:1.5rem;margin:0}.note{background:#eaf2ff;border:1px solid #b9cff7;border-radius:10px;padding:14px 18px;color:#23416b;margin-bottom:1rem}.metric-card{border:1px solid #dbe3ed;border-radius:12px;background:#fff;padding:16px 18px;min-height:112px}.metric-label{color:#63738a;font-size:.9rem}.metric-value{font-size:1.7rem;font-weight:750;color:#10233f;margin:.25rem 0}.metric-sub{font-size:.82rem;color:#63738a}.calendar-grid{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));border-left:1px solid #dbe3ed;border-top:1px solid #dbe3ed}.cal-cell{min-height:125px;background:white;border-right:1px solid #dbe3ed;border-bottom:1px solid #dbe3ed;padding:6px;overflow-wrap:anywhere}.cal-out{background:#f7f9fc;color:#9aa5b3}.cal-today{background:#f0f5ff;box-shadow:inset 0 0 0 2px #8bb0f0}.cal-day{font-size:.8rem;font-weight:700;margin-bottom:4px}.cal-event{font-size:.68rem;line-height:1.3;padding:4px;margin:3px 0;border-radius:4px;display:block;text-decoration:none}.cal-event.kr{background:#eaf6f1;color:#27614a}.cal-event.us{background:#edf3ff;color:#234a91}.cal-event.jp{background:#f8edfb;color:#733c83}.news-card{border:1px solid #dbe3ed;border-radius:10px;padding:12px 15px;margin:.6rem 0;background:#fff}.small-muted{color:#63738a;font-size:.85rem}@media(max-width:700px){.cal-cell{min-height:80px;padding:3px}.cal-event{font-size:0;padding:3px 1px;text-align:center}.cal-event:after{content:'●';font-size:8px}.cal-day{font-size:.7rem}}
</style>
<div class="topbar"><h1>조달금리 조회 페이지</h1></div>
""", unsafe_allow_html=True)


def _database_url():
    return st.secrets.get("database_url") or os.environ.get("DATABASE_URL")


def _connect_db():
    import psycopg
    url = _database_url().replace("postgresql+psycopg://", "postgresql://", 1)
    return psycopg.connect(url)


def load_db():
    url = _database_url()
    if url:
        with _connect_db() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS procurement_state (id INTEGER PRIMARY KEY, payload JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())")
            conn.execute("CREATE TABLE IF NOT EXISTS procurement_backups (id BIGSERIAL PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), payload JSONB NOT NULL)")
            row = conn.execute("SELECT payload FROM procurement_state WHERE id=1").fetchone()
            if row:
                return row[0], "PostgreSQL 영구 저장"
            base = json.loads(DATA_PATH.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO procurement_state (id,payload) VALUES (1,%s)", (Jsonb(base),))
            return base, "PostgreSQL 영구 저장"
    return json.loads(DATA_PATH.read_text(encoding="utf-8")), "로컬 JSON 저장 (Community Cloud에서는 영구 저장 보장 안 됨)"


def save_db(db):
    url = _database_url()
    if url:
        with _connect_db() as conn:
            old = conn.execute("SELECT payload FROM procurement_state WHERE id=1").fetchone()
            if old:
                conn.execute("INSERT INTO procurement_backups(payload) VALUES (%s)", (Jsonb(old[0]),))
                conn.execute("DELETE FROM procurement_backups WHERE created_at < now() - interval '30 days'")
            conn.execute("INSERT INTO procurement_state(id,payload,updated_at) VALUES (1,%s,now()) ON CONFLICT(id) DO UPDATE SET payload=EXCLUDED.payload,updated_at=now()", (Jsonb(db),))
    else:
        BACKUP_DIR.mkdir(exist_ok=True)
        if DATA_PATH.exists():
            stamp = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
            (BACKUP_DIR / f"data_{stamp}.json").write_text(DATA_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        DATA_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def kst_today():
    return datetime.now(KST).date()


def rate(record):
    if not record or record.get("status") != "normal" or not isinstance(record.get("rateMilli"), int):
        return None
    return record["rateMilli"] / 1000


def display_round(value):
    if value is None:
        return None
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def format_rate(value):
    return "확인필요" if value is None else f"{display_round(value):.2f}%"


def records_for(db, d, product):
    return [r for r in db.get("records", []) if r.get("date") == d and r.get("product") == product]


def get_dates(db, start, end, products):
    return sorted({r["date"] for r in db.get("records", []) if r.get("product") in products and start <= r.get("date", "") <= end})


def average(records, providers):
    values = []
    for provider in providers:
        found = next((r for r in records if r.get("provider") == provider), None)
        value = rate(found)
        if value is None:
            return None
        values.append(value)
    return sum(values) / len(values) if values else None


def plot_line(labels, series, title, news=None):
    fig = go.Figure()
    all_values = []
    for item in series:
        all_values.extend([v for v in item["values"] if v is not None])
        fig.add_trace(go.Scatter(x=labels, y=item["values"], mode="lines+markers", name=item["name"], line={"color": item["color"], "width": 2.5}, connectgaps=False, hovertemplate="%{x}<br>" + item["name"] + ": %{y:.2f}%<extra></extra>"))
    if all_values:
        low, high = min(all_values), max(all_values)
        padding = max((high - low) * .14, .025)
        fig.update_yaxes(range=[low-padding, high+padding], title="연 %")
    if news:
        idx_dates = [str(x) for x in labels]
        for i, item in enumerate(news, 1):
            d = item.get("plot_date", item["date"])
            if d not in idx_dates:
                continue
            fig.add_vline(x=d, line_width=1, line_dash="dot", line_color="#d38b31", opacity=.7)
            point_index=idx_dates.index(d)
            point_y=next((s["values"][point_index] for s in series if point_index<len(s["values"]) and s["values"][point_index] is not None),None)
            if point_y is not None:
                fig.add_trace(go.Scatter(x=[d], y=[point_y], mode="markers+text", name=f"뉴스 {i}", text=[str(i)], textposition="top center", marker={"color":"#d38b31","size":10,"symbol":"diamond"}, customdata=[[item["date"],item["title"]]], hovertemplate="%{customdata[0]} · %{customdata[1]}<extra></extra>"))
    fig.update_layout(title=title, height=390, margin={"l":10,"r":10,"t":40,"b":10}, hovermode="x unified", legend={"orientation":"h","yanchor":"bottom","y":1.02,"xanchor":"left","x":0}, xaxis={"title":""}, yaxis={"gridcolor":"#e5eaf0"}, plot_bgcolor="white", paper_bgcolor="white")
    return fig


def selected_provider_set(avg_mode):
    if avg_mode == "3사 평균":
        return PROVIDER_ORDER[:3]
    if avg_mode == "4사 평균":
        return PROVIDER_ORDER
    return [next(k for k,v in PROVIDER_NAMES.items() if v == avg_mode)]


# Load source once per Streamlit session. The collector itself only records dates shown by providers.
if "db" not in st.session_state:
    try:
        st.session_state.db, st.session_state.persistence_label = load_db()
    except Exception as exc:
        st.error(f"데이터 저장소 연결 실패: {exc}")
        st.stop()
db = st.session_state.db
persistence_label = st.session_state.persistence_label

today = kst_today()
month_start = today.replace(day=1)
month_dates = [d for d in get_dates(db, month_start.isoformat(), today.isoformat(), list(PRODUCTS))]
latest = date.fromisoformat(month_dates[-1]) if month_dates else today

with st.sidebar:
    st.header("조회 조건")
    default_start = month_start
    start_date = st.date_input("조회 시작일", value=default_start, min_value=month_start, max_value=today)
    end_date = st.date_input("조회 종료일", value=latest, min_value=month_start, max_value=today)
    product_label = st.selectbox("채권", list(PRODUCT_OPTIONS.keys()))
    avg_options = ["3사 평균", "4사 평균", *PROVIDER_NAMES.values()]
    avg_mode = st.selectbox("조회 방식", avg_options)
    selected_providers = st.multiselect("평가사 열 선택", PROVIDER_ORDER, default=PROVIDER_ORDER, format_func=lambda p: PROVIDER_NAMES[p])
    chart_options = ["조회 방식", "3사 평균", "4사 평균", *PROVIDER_NAMES.values()]
    extra_series = st.multiselect("그래프에 추가할 계열", chart_options[1:], default=[])
    st.caption("기본 그래프에는 조회 방식의 계열이 표시됩니다.")
    st.divider()
    collect_clicked = st.button("실시간 금리 업데이트", type="primary", use_container_width=True)
    st.caption("수집은 각 평가사 화면에 표시된 기준일을 읽습니다. 실패하거나 항목을 특정할 수 없으면 확인필요로 남깁니다.")
    st.caption("저장 방식: " + persistence_label)
    if not _database_url():
        st.warning("배포 환경에서는 로컬 파일의 보존이 보장되지 않습니다. 계속 보관하려면 secrets에 PostgreSQL database_url을 설정하세요.")

if start_date > end_date:
    st.error("조회 시작일은 종료일보다 늦을 수 없습니다.")
    st.stop()

if collect_clicked:
    try:
        with st.spinner("Playwright 브라우저를 준비하고 평가사 4곳을 순서대로 조회합니다. 첫 실행은 브라우저 다운로드로 더 오래 걸릴 수 있습니다."):
            os.environ["PROCUREMENT_USE_BUNDLED_CHROMIUM"] = "1"
            # Install the bundled headless browser only on first cloud collection.
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser_path = Path(p.chromium.executable_path)
            if not browser_path.exists():
                subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], cwd=ROOT, check=True, timeout=240)
            current_db, persistence_label = load_db()
            st.session_state.persistence_label = persistence_label
            updated, run = collect_latest(current_db, kst_now())
            save_db(updated)
            st.session_state.db = updated
            st.session_state.last_collection = run
            st.session_state.pop("collection_error", None)
            st.success("수집 및 저장을 완료했습니다. 상태: " + run.get("status", "확인필요"))
        st.rerun()
    except Exception as exc:
        st.session_state.collection_error = str(exc)
if st.session_state.get("collection_error"):
    st.error("수집 또는 저장 실패: " + st.session_state.collection_error)

if "last_collection" in st.session_state:
    run = st.session_state.last_collection
    results = " · ".join(f"{p.get('name',p.get('provider'))}: {p.get('date','기준일 확인필요')} {p.get('status')}" for p in run.get("providers", []))
    st.info("최근 실행 " + run.get("status", "") + (" · " + results if results else ""))

st.markdown("<div class='note'>조회 화면의 기준 범위는 실행 당월입니다. 기간 평균은 저장된 관측일을 바탕으로 계산하고, 스프레드는 표시 금리를 소수점 둘째 자리로 반올림한 뒤 차이를 bp로 환산합니다.</div>", unsafe_allow_html=True)

products = list(PRODUCTS) if product_label == "금융채 + 국채 동시 조회" else [PRODUCT_OPTIONS[product_label]]
provider_set = selected_provider_set(avg_mode)
start_iso, end_iso = start_date.isoformat(), end_date.isoformat()
daily_dates = get_dates(db, start_iso, end_iso, products)

# Summary cards always show both products and the spread, regardless of the chart filter.
summary_values = []
for product in PRODUCTS:
    dates = get_dates(db, start_iso, end_iso, [product])
    vals = [average(records_for(db,d,product), provider_set) for d in dates]
    avg_value = sum(vals)/len(vals) if vals and all(v is not None for v in vals) else None
    summary_values.append((avg_value, len(dates)))
fin_value, fin_count = summary_values[0]
gov_value, gov_count = summary_values[1]
display_fin = float(Decimal(str(fin_value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if fin_value is not None else None
display_gov = float(Decimal(str(gov_value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if gov_value is not None else None
spread = (display_fin-display_gov)*100 if display_fin is not None and display_gov is not None else None
kpis = st.columns(3)
for col,(label,value,count) in zip(kpis,[
    ("금융채 기간평균",fin_value,fin_count),
    ("국채 기간평균",gov_value,gov_count),
    ("금융채-국채 스프레드",spread,None),
]):
    if label.endswith("스프레드"):
        value_text = "확인필요" if value is None else f"{value:+.0f}bp"
        sub = "금융채·국채 표시 기간평균 차이"
    else:
        value_text = format_rate(value)
        sub = f"{count}개 관측일" + (" · 선택 평균 구성값 누락" if value is None else "")
    col.markdown(f"<div class='metric-card'><div class='metric-label'>{label}</div><div class='metric-value'>{value_text}</div><div class='metric-sub'>{sub}</div></div>", unsafe_allow_html=True)

if not daily_dates:
    st.warning("선택 기간에 저장된 관측값이 없습니다. 없는 금리는 생성하지 않았습니다.")
else:
    st.caption(f"{start_iso} ~ {end_iso} · {product_label} · {avg_mode} · 평균은 선택한 평가사 조합의 원 정밀도 값으로 계산")


def chart_series_for(product_list, dates, modes):
    series = []
    for product in product_list:
        for mode in modes:
            if mode == "조회 방식":
                providers = provider_set
                name = f"{PRODUCTS[product]} · {avg_mode}"
                color = "#123b7a" if product == "financial_aa_minus_3y" else "#087f8c"
                values = [average(records_for(db,d,product),providers) for d in dates]
            elif mode in ("3사 평균", "4사 평균"):
                providers = PROVIDER_ORDER[:3] if mode == "3사 평균" else PROVIDER_ORDER
                name, color = f"{PRODUCTS[product]} · {mode}", "#597cae" if mode == "3사 평균" else "#172b4d"
                values = [average(records_for(db,d,product),providers) for d in dates]
            else:
                provider = next(k for k,v in PROVIDER_NAMES.items() if v == mode)
                name, color = f"{PRODUCTS[product]} · {mode}", PROVIDER_COLORS[provider]
                values = [rate(next((r for r in records_for(db,d,product) if r.get("provider")==provider),None)) for d in dates]
            series.append({"name":name,"color":color,"values":values})
    return series


tab_daily, tab_monthly, tab_calendar, tab_review = st.tabs(["일별 금리 추이", "월별 금리 추이", "주요 금융 일정", "전월 금융 리뷰"])

with tab_daily:
    st.subheader("일별 금리 추이")
    daily_modes = ["조회 방식", *extra_series]
    ds_series = chart_series_for(products, daily_dates, daily_modes)
    fig = plot_line(daily_dates, ds_series, "일별 금리 추이")
    st.plotly_chart(fig, use_container_width=True, key="daily_chart")
    st.markdown("**평가사 원문 링크:** " + " · ".join(f"[{PROVIDER_NAMES[p]} ↗]({PROVIDER_URLS[p]})" for p in selected_providers))
    rows = []
    for d in daily_dates:
        for product in products:
            recs = records_for(db,d,product)
            if not recs:
                continue
            current = average(recs,provider_set)
            prior_dates = sorted({r["date"] for r in db.get("records",[]) if r.get("product")==product and r.get("date","")<d})
            prior_date = prior_dates[-1] if prior_dates else None
            prior_value = average(records_for(db,prior_date,product),provider_set) if prior_date else None
            missing = [p for p in provider_set if rate(next((r for r in recs if r.get("provider")==p),None)) is None]
            reasons=[]
            if missing: reasons.append("현재 평균 구성값 누락: "+", ".join(PROVIDER_NAMES[p] for p in missing))
            if prior_date is None: reasons.append("이전 관측일 없음")
            elif prior_value is None:
                prior_records=records_for(db,prior_date,product)
                pm=[p for p in provider_set if rate(next((r for r in prior_records if r.get("provider")==p),None)) is None]
                reasons.append(f"직전 관측일 {prior_date} 구성값 누락: "+", ".join(PROVIDER_NAMES[p] for p in pm))
            change=(current-prior_value)*100 if current is not None and prior_value is not None else None
            row={"공시일":d,"채권":PRODUCTS[product]}
            for p in selected_providers:
                r=next((r for r in recs if r.get("provider")==p),None)
            row[PROVIDER_NAMES[p]]=format_rate(rate(r))
            row["평균/조회값"]=format_rate(current) if current is not None else "확인필요: "+("누락 "+", ".join(PROVIDER_NAMES[p] for p in missing) if missing else "원자료 확인")
            row["전일 대비"]=f"{change:+.1f}bp" if change is not None else "확인필요: "+("; ".join(reasons) or "비교값 없음")
            row["상태"]="정상" if not missing else "확인필요: "+reasons[0]
            rows.append(row)
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

with tab_monthly:
    st.subheader(f"{today.year}년 월별 금리 추이")
    month_labels=[f"{today.year}-{m:02d}" for m in range(1,13)]
    monthly_values={product:[] for product in PRODUCTS}
    month_counts=[]
    for ym in month_labels:
        m_start=date.fromisoformat(ym+"-01")
        m_end=date(m_start.year,m_start.month,calendar.monthrange(m_start.year,m_start.month)[1])
        dates=get_dates(db,m_start.isoformat(),min(m_end,today).isoformat(),list(PRODUCTS)) if m_start<=today else []
        month_counts.append(len(dates))
        for product in PRODUCTS:
            dps=get_dates(db,m_start.isoformat(),min(m_end,today).isoformat(),[product]) if m_start<=today else []
            vals=[average(records_for(db,d,product),provider_set) for d in dps]
            monthly_values[product].append(sum(vals)/len(vals) if vals and all(v is not None for v in vals) else None)
    monthly_series=[]
    m_modes=["조회 방식",*extra_series]
    for product in products:
        for mode in m_modes:
            if mode=="조회 방식": providers=provider_set; display=avg_mode; color="#123b7a" if product=="financial_aa_minus_3y" else "#087f8c"
            elif mode=="3사 평균": providers=PROVIDER_ORDER[:3]; display=mode; color="#597cae"
            elif mode=="4사 평균": providers=PROVIDER_ORDER; display=mode; color="#172b4d"
            else:
                providers=[next(k for k,v in PROVIDER_NAMES.items() if v==mode)]; display=mode; color=PROVIDER_COLORS[providers[0]]
            month_values=[]
            for ym in month_labels:
                m_start=date.fromisoformat(ym+"-01");m_end=min(date(m_start.year,m_start.month,calendar.monthrange(m_start.year,m_start.month)[1]),today)
                ds=get_dates(db,m_start.isoformat(),m_end.isoformat(),[product]) if m_start<=today else []
                daily=[average(records_for(db,d,product),providers) for d in ds]
                month_values.append(sum(daily)/len(daily) if daily and all(v is not None for v in daily) else None)
            monthly_series.append({"name":f"{PRODUCTS[product]} · {display}","color":color,"values":month_values})
    mfig=plot_line(month_labels,monthly_series,"월별 기간평균 금리")
    st.plotly_chart(mfig,use_container_width=True,key="monthly_chart")
    table=[]
    for i,ym in enumerate(month_labels):
        fin,gov=monthly_values["financial_aa_minus_3y"][i],monthly_values["government_3y"][i]
        prev_fin=monthly_values["financial_aa_minus_3y"][i-1] if i else None
        prev_gov=monthly_values["government_3y"][i-1] if i else None
        sp=(display_round(fin)-display_round(gov))*100 if fin is not None and gov is not None else None
        status="예정" if ym>today.strftime("%Y-%m") else "정상" if fin is not None and gov is not None else "확인필요"
        table.append({"월":ym,"관측일":month_counts[i],"금융채 월평균":format_rate(fin),"국채 월평균":format_rate(gov),"금융채-국채 스프레드":"확인필요" if sp is None else f"{sp:+.0f}bp","금융채 전월 대비":"—" if prev_fin is None else "확인필요" if fin is None or prev_fin is None else f"{(fin-prev_fin)*100:+.1f}bp","국채 전월 대비":"—" if prev_gov is None else "확인필요" if gov is None or prev_gov is None else f"{(gov-prev_gov)*100:+.1f}bp","상태":status})
    st.dataframe(pd.DataFrame(table),hide_index=True,use_container_width=True)
    st.caption("스프레드는 표시된 두 월평균을 각각 소수점 둘째 자리까지 반올림한 뒤 차이를 bp로 환산합니다. 전월 대비는 원 정밀도 월평균 변화입니다.")

with tab_calendar:
    ym=today.strftime("%Y-%m")
    st.subheader(f"{today.year}년 {today.month}월 주요 금융 일정")
    weekday_names=["일","월","화","수","목","금","토"]
    cols=st.columns(7)
    for col,name in zip(cols,weekday_names): col.markdown(f"**{name}**")
    month_events=[e for e in CALENDAR_EVENTS if e["date"].startswith(ym)]
    first=date(today.year,today.month,1)
    offset=(first.weekday()+1)%7
    days_in_month=calendar.monthrange(today.year,today.month)[1]
    total=((offset+days_in_month+6)//7)*7
    for week in range(total//7):
        cols=st.columns(7)
        for weekday,col in enumerate(cols):
            n=week*7+weekday-offset+1
            if 1<=n<=days_in_month:
                cell_date=date(today.year,today.month,n)
                iso=cell_date.isoformat()
                cls="cal-cell cal-today" if cell_date==today else "cal-cell"
                pieces=[f"<div class='{cls}'><div class='cal-day'>{n}{' · 오늘' if cell_date==today else ''}</div>"]
                for event in [e for e in month_events if e["date"]==iso]:
                    pieces.append(f"<a class='cal-event {event['class']}' href='{event['url']}' target='_blank'><b>{html.escape(event['area'])}</b><br>{html.escape(event['title'])}<br><small>{html.escape(event['time'])}</small></a>")
                pieces.append("</div>")
                col.markdown("".join(pieces),unsafe_allow_html=True)
            else:
                col.markdown("<div class='cal-cell cal-out'>&nbsp;</div>",unsafe_allow_html=True)
    if ym=="2026-11":
        st.caption("BLS, 연방준비제도, 일본은행, 한국은행의 공식 일정과 대조했습니다. BOJ의 11월 정책회의는 없으며 10월 회의 의견 요약이 11월 10일 공개됐습니다. 날짜별 일정을 누르면 출처로 이동합니다.")
    else:
        st.caption("현재 달의 공식 발표 캘린더가 코드에 등록되어 있지 않으면 빈 달력으로 표시됩니다. 이 목록은 자동 갱신되지 않습니다.")

with tab_review:
    previous_month=(today.replace(day=1)-timedelta(days=1)).strftime("%Y-%m")
    st.subheader(f"{previous_month[:4]}년 {int(previous_month[5:])}월 전월 금융 리뷰")
    review_start=date.fromisoformat(previous_month+"-01")
    review_end=date(review_start.year,review_start.month,calendar.monthrange(review_start.year,review_start.month)[1])
    review_dates=get_dates(db,review_start.isoformat(),review_end.isoformat(),products)
    review_series=chart_series_for(products,review_dates,["조회 방식",*extra_series])
    month_news=[dict(n) for n in PREVIOUS_MONTH_NEWS if n["date"].startswith(previous_month)]
    for item in month_news:
        valid=[d for d in review_dates if records_for(db,d,products[0])]
        item["plot_date"]=min(valid,key=lambda d:abs((date.fromisoformat(d)-date.fromisoformat(item["date"])).days)) if valid else item["date"]
    summary=[]
    for product in products:
        vals=[average(records_for(db,d,product),provider_set) for d in review_dates]
        good=[v for v in vals if v is not None]
        summary.append(f"{PRODUCTS[product]} {len(good)}개 관측일 · "+(f"{format_rate(good[0])} → {format_rate(good[-1])}" if good else "관측값 확인필요"))
    st.caption(" · ".join(summary) if summary else "전월 관측 자료 없음")
    review_fig=plot_line(review_dates,review_series,"전월 금리와 주요 뉴스",month_news)
    st.plotly_chart(review_fig,use_container_width=True,key="review_chart")
    st.caption("차트의 주황색 뉴스 표식에 커서를 두면 해당 시기의 뉴스가 표시됩니다. 뉴스와 금리 변화의 인과관계를 뜻하지 않습니다.")
    if month_news:
        for i,item in enumerate(month_news,1):
            links=" · ".join(f"<a href=\"{url}\" target=\"_blank\" rel=\"noreferrer\">{html.escape(name)} ↗</a>" for name,url in item["sources"])
            st.markdown(f"<div class='news-card'><b>{item['date']} · 차트 뉴스 {i} · {html.escape(item['title'])}</b><br>{html.escape(item['summary'])}<br>{links}</div>",unsafe_allow_html=True)
    else:
        st.info("해당 월에 등록된 중복 검토 뉴스가 없습니다.")

st.divider()
st.subheader("다운로드 및 자료 상태")
export_rows=[]
for d in daily_dates:
    for product in products:
        recs=records_for(db,d,product)
        if not recs: continue
        row={"공시일":d,"채권":PRODUCTS[product]}
        for p in selected_providers:
            r=next((x for x in recs if x.get("provider")==p),None)
            row[PROVIDER_NAMES[p]]=None if rate(r) is None else display_round(rate(r))
        value=average(recs,provider_set)
        row["조회 평균"]=None if value is None else display_round(value)
        row["상태"]="정상" if value is not None else "확인필요"
        export_rows.append(row)
csv=pd.DataFrame(export_rows).to_csv(index=False,encoding="utf-8-sig") if export_rows else "공시일,채권,상태\n"
st.download_button("엑셀 다운로드 (CSV)",csv,file_name=f"조달금리_{start_iso}_{end_iso}.csv",mime="text/csv",type="primary")
last_date=max((r.get("date","") for r in db.get("records",[])),default="없음")
latest_run=db.get("runs",[])[-1] if db.get("runs") else {}
st.caption(f"기준일 {today.isoformat()} · 저장된 마지막 관측일 {last_date} · 레코드 {len(db.get('records',[]))}건 · 최근 수집 {latest_run.get('status','미실행')} · 저장 방식 {persistence_label}")
