import os
import re
import csv
import glob
import datetime as dt
from typing import List, Dict, Tuple
from collections import defaultdict

# ===== Selenium + BS4 =====
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
from urllib.parse import urljoin


# -------------------------------
# 유틸
# -------------------------------
def now_kst() -> dt.datetime:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))


def ensure_data_dir():
    os.makedirs("data", exist_ok=True)


def _to_float2(s: str) -> float:
    if not s:
        return 0.0
    m = re.findall(r"[0-9\.,]+", s)
    if not m:
        return 0.0
    try:
        return round(float(m[0].replace(",", "")), 2)
    except:
        return 0.0


# -------------------------------
# 오래된 파일 정리
# -------------------------------
def cleanup_old_csv_files(days: int = 3):
    today = now_kst().date()
    pattern = re.compile(r"naver_top_searchratio_(\d{8})_(\d{4})\.csv$")
    for fp in glob.glob("data/naver_top_searchratio_*.csv"):
        m = pattern.search(os.path.basename(fp))
        if not m:
            continue
        d = dt.datetime.strptime(m.group(1), "%Y%m%d").date()
        if (today - d).days > days:
            os.remove(fp)


def cleanup_old_txt_files(days: int = 14):
    today = now_kst().date()
    pattern = re.compile(r"daily_top30_(\d{8})\.txt$")
    for fp in glob.glob("data/daily_top30_*.txt"):
        m = pattern.search(os.path.basename(fp))
        if not m:
            continue
        d = dt.datetime.strptime(m.group(1), "%Y%m%d").date()
        if (today - d).days > days:
            os.remove(fp)


# -------------------------------
# 1) 인기검색 크롤링
# -------------------------------
def fetch_top30_search_ratio() -> List[Dict]:
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    base_url = "https://finance.naver.com/sise/lastsearch2.naver"
    driver.get(base_url)

    WebDriverWait(driver, 5).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "table.type_5"))
    )

    soup = BeautifulSoup(driver.page_source, "html.parser")
    driver.quit()

    table = soup.select_one("table.type_5")

    rows = []
    ts = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    rank = 0

    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue

        name = tds[1].get_text(strip=True)
        score = _to_float2(tds[-1].get_text(strip=True))

        rank += 1
        rows.append({
            "rank": rank,
            "name": name,
            "score": f"{score:.2f}",
            "ts": ts
        })
        if rank >= 30:
            break

    return rows


# -------------------------------
# 2) CSV 저장
# -------------------------------
def save_snapshot_csv(rows: List[Dict]):
    ensure_data_dir()
    fn = f"data/naver_top_searchratio_{now_kst().strftime('%Y%m%d_%H%M')}.csv"
    with open(fn, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["rank", "name", "score", "ts"])
        w.writeheader()
        w.writerows(rows)

    cleanup_old_csv_files(3)


# -------------------------------
# 3) 최근 N개 CSV 목록
# -------------------------------
FNAME_RE = re.compile(r"naver_top_searchratio_(\d{8})_(\d{4})\.csv$")


def list_recent_snapshots(limit: int = 12, ref_date: dt.date | None = None) -> List[str]:
    files = glob.glob("data/naver_top_searchratio_*.csv")

    def _key(fp: str):
        m = FNAME_RE.search(os.path.basename(fp))
        if not m:
            return ("00000000", "0000")
        return m.group(1), m.group(2)

    files = sorted(files, key=_key, reverse=True)

    if ref_date:
        files = [
            f for f in files
            if dt.datetime.strptime(_key(f)[0], "%Y%m%d").date() <= ref_date
        ]

    return files[:limit]


# -------------------------------
# 4) CSV 합계 계산 (변경 없음)
# -------------------------------
def aggregate_scores_from_files(files: List[str]) -> Dict[str, float]:
    acc = defaultdict(float)
    for fp in files:
        with open(fp, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                acc[row["name"]] += float(row["score"])
    return acc


# -------------------------------
# 5) daily_top30 + 비교
# -------------------------------
def save_daily_top30_txt(today_map: Dict[str, float]):
    ensure_data_dir()
    today = now_kst().date()
    out_fn = f"data/daily_top30_{today.strftime('%Y%m%d')}.txt"

    past_maps: Dict[int, Dict[str, float]] = {}

    for d in range(1, 8):
        ref_date = today - dt.timedelta(days=d)
        files = list_recent_snapshots(12, ref_date)
        if files:
            past_maps[d] = aggregate_scores_from_files(files)
        else:
            past_maps[d] = {}

    top = sorted(today_map.items(), key=lambda x: -x[1])[:30]

    lines = []
    lines.append("[네이버 인기검색 합계 Top30] (최근 12 CSV 합계)")
    lines.append(f"생성시각: {now_kst().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("-" * 60)

    for i, (name, total) in enumerate(top, 1):
        lines.append(f"{i:2d}. {name} | 합계: {total:.2f}")

        comps = []
        for d in range(1, 8):
            prev_map = past_maps[d]
            if name not in prev_map:
                comps.append(f"D-{d}: NEW")
            else:
                prev = prev_map[name]
                chg = (total - prev) / prev * 100
                if chg > 0:
                    comps.append(f"D-{d}: ▲ +{chg:.2f}%")
                elif chg < 0:
                    comps.append(f"D-{d}: ▼ {chg:.2f}%")
                else:
                    comps.append(f"D-{d}: 0.00%")

        lines.append("     " + "  ".join(comps))

    with open(out_fn, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(lines))

    cleanup_old_txt_files(14)


# -------------------------------
# 메인
# -------------------------------
if __name__ == "__main__":
    rows = fetch_top30_search_ratio()
    save_snapshot_csv(rows)

    today_files = list_recent_snapshots(12)
    score_map = aggregate_scores_from_files(today_files)
    save_daily_top30_txt(score_map)
