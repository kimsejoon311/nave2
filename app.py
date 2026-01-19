import os
import re
import csv
import glob
import datetime as dt
from collections import defaultdict
from typing import Dict, List

# ===== Selenium / BS4 =====
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup


# ---------------------------
# 기본 유틸
# ---------------------------
def now_kst() -> dt.datetime:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))


def ensure_data_dir():
    os.makedirs("data", exist_ok=True)


def to_float(s: str) -> float:
    try:
        return float(s.replace(",", "").replace("%", ""))
    except:
        return 0.0


# ---------------------------
# 오래된 파일 정리
# ---------------------------
def cleanup_old_csv(days: int = 3):
    today = now_kst().date()
    for fp in glob.glob("data/naver_top_searchratio_*.csv"):
        m = re.search(r"_(\d{8})_", fp)
        if not m:
            continue
        d = dt.datetime.strptime(m.group(1), "%Y%m%d").date()
        if (today - d).days > days:
            os.remove(fp)


def cleanup_old_txt(days: int = 14):
    today = now_kst().date()
    for fp in glob.glob("data/daily_top30_*.txt"):
        m = re.search(r"_(\d{8})\.txt$", fp)
        if not m:
            continue
        d = dt.datetime.strptime(m.group(1), "%Y%m%d").date()
        if (today - d).days > days:
            os.remove(fp)


# ---------------------------
# 1) 네이버 인기검색 크롤링
# ---------------------------
def fetch_top30() -> List[Dict]:
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

    driver.get("https://finance.naver.com/sise/lastsearch2.naver")

    WebDriverWait(driver, 5).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "table.type_5"))
    )

    soup = BeautifulSoup(driver.page_source, "html.parser")
    driver.quit()

    rows = []
    ts = now_kst().strftime("%Y-%m-%d %H:%M:%S")

    for tr in soup.select("table.type_5 tbody tr")[:30]:
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue
        name = tds[1].get_text(strip=True)
        score = to_float(tds[-1].get_text(strip=True))
        rows.append({
            "name": name,
            "score": round(score, 2),
            "ts": ts
        })

    return rows


# ---------------------------
# 2) 스냅샷 CSV 저장
# ---------------------------
def save_snapshot(rows: List[Dict]):
    ensure_data_dir()
    fn = f"data/naver_top_searchratio_{now_kst().strftime('%Y%m%d_%H%M')}.csv"
    with open(fn, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["name", "score", "ts"])
        w.writeheader()
        w.writerows(rows)

    cleanup_old_csv()


# ---------------------------
# 3) 최근 12개 CSV 합산
# ---------------------------
def aggregate_last_12() -> Dict[str, float]:
    files = sorted(
        glob.glob("data/naver_top_searchratio_*.csv"),
        reverse=True
    )[:12]

    acc = defaultdict(float)
    for fp in files:
        with open(fp, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                acc[r["name"]] += float(r["score"])

    return acc


# ---------------------------
# 4) 과거 daily 파일 로드
# ---------------------------
def load_daily(date: str) -> Dict[str, float]:
    fn = f"data/daily_top30_{date}.txt"
    if not os.path.exists(fn):
        return {}

    data = {}
    with open(fn, encoding="utf-8-sig") as f:
        for line in f:
            if "| 합계:" in line:
                name = line.split(".")[1].split("|")[0].strip()
                total = float(line.split("합계:")[1].strip())
                data[name] = total
    return data


# ---------------------------
# 5) daily_top30 생성 (비교 포함)
# ---------------------------
def save_daily_top30(today_map: Dict[str, float]):
    ensure_data_dir()
    today = now_kst().strftime("%Y%m%d")

    past = {
        d: load_daily((now_kst() - dt.timedelta(days=d)).strftime("%Y%m%d"))
        for d in range(1, 8)
    }

    top30 = sorted(today_map.items(), key=lambda x: -x[1])[:30]

    lines = []
    lines.append("[네이버 인기검색 합계 Top30]")
    lines.append(f"생성시각: {now_kst().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("-" * 60)

    for i, (name, total) in enumerate(top30, 1):
        lines.append(f"{i:2d}. {name} | 합계: {total:.2f}")

        comps = []
        for d in range(1, 8):
            prev_map = past[d]
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

    out = f"data/daily_top30_{today}.txt"
    with open(out, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(lines))

    cleanup_old_txt()


# ---------------------------
# 메인
# ---------------------------
if __name__ == "__main__":
    rows = fetch_top30()
    save_snapshot(rows)

    score_map = aggregate_last_12()
    save_daily_top30(score_map)
