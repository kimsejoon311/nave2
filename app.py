import os
import re
import csv
import glob
import datetime as dt
from typing import List, Dict, Tuple
from collections import defaultdict

# ===== [Selenium + BS4] : 인기검색 Top30 (종목명, 검색비율 점수) =====
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
    """'12.345%', '1,234.5' 등을 float로 변환 후 소수 둘째 반올림"""
    if not s:
        return 0.0
    m = re.findall(r"[0-9\.,]+", s)
    if not m:
        return 0.0
    v = m[0].replace(",", "")
    try:
        return round(float(v), 2)
    except:
        return 0.0


# -------------------------------
# (수정됨) 오래된 파일 정리 (CSV: 3일만 유지)
# -------------------------------
def cleanup_old_csv_files(days: int = 3):
    ensure_data_dir()
    today = now_kst().date()
    pattern = re.compile(r"naver_top_searchratio_(\d{8})_(\d{4})\.csv$")
    deleted = 0

    for fp in glob.glob("data/naver_top_searchratio_*.csv"):
        m = pattern.search(os.path.basename(fp))
        if not m:
            continue
        date_str = m.group(1)
        try:
            file_date = dt.datetime.strptime(date_str, "%Y%m%d").date()
        except:
            continue
        if (today - file_date).days > days:
            try:
                os.remove(fp)
                deleted += 1
                print(f"🗑️ CSV 삭제됨: {fp}")
            except Exception as e:
                print(f"⚠️ CSV 삭제 실패: {fp} ({e})")


def cleanup_old_txt_files(days: int = 14):
    """TXT는 기존처럼 14일 보관"""
    ensure_data_dir()
    today = now_kst().date()
    pattern = re.compile(r"daily_top30_(\d{8})\.txt$")
    deleted = 0

    for fp in glob.glob("data/daily_top30_*.txt"):
        m = pattern.search(os.path.basename(fp))
        if not m:
            continue
        date_str = m.group(1)
        try:
            file_date = dt.datetime.strptime(date_str, "%Y%m%d").date()
        except:
            continue
        if (today - file_date).days > days:
            try:
                os.remove(fp)
                deleted += 1
                print(f"🗑️ TXT 삭제됨: {fp}")
            except Exception as e:
                print(f"⚠️ TXT 삭제 실패: {fp} ({e})")


# -------------------------------
# 1) 인기종목 크롤링 (검색비율만 점수화)
# -------------------------------
def fetch_top30_search_ratio() -> List[Dict]:
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    base_url = "https://finance.naver.com/sise/lastsearch2.naver"
    driver.get(base_url)

    def _find_table_in_current_page() -> bool:
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table.type_5"))
            )
            return True
        except Exception:
            return False

    table_found = False

    # 1) 메인 DOM 시도
    if _find_table_in_current_page():
        table_found = True
    else:
        # 2) iframe 내부 확인
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_all_elements_located((By.TAG_NAME, "iframe"))
            )
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
        except Exception:
            iframes = []

        for f in iframes:
            try:
                driver.switch_to.frame(f)
                if _find_table_in_current_page():
                    table_found = True
                    break
                src = f.get_attribute("src")
                driver.switch_to.default_content()
                if src:
                    driver.get(urljoin(base_url, src))
                    if _find_table_in_current_page():
                        table_found = True
                        break
                    driver.get(base_url)
            except Exception:
                driver.switch_to.default_content()
                continue

    if not table_found:
        driver.quit()
        raise RuntimeError("표를 찾을 수 없습니다.")

    soup = BeautifulSoup(driver.page_source, "html.parser")
    driver.quit()

    table = soup.select_one("table.type_5")
    if not table:
        raise RuntimeError("테이블 파싱 실패")

    # 헤더 분석
    header_candidates = table.select("thead tr")
    if not header_candidates:
        header_candidates = table.select("tr")[:3]

    best_hdr = max(header_candidates, key=lambda tr: len(tr.find_all(["th", "td"]))) if header_candidates else None

    headers, header_map = [], {}
    if best_hdr:
        for idx, th in enumerate(best_hdr.find_all(["th", "td"])):
            txt = th.get_text(" ", strip=True).replace("\xa0", " ").strip()
            txt_norm = "".join(txt.split())
            headers.append(txt_norm)
            if txt_norm:
                header_map[txt_norm] = idx

    ratio_idx = -1
    for i, h in enumerate(headers):
        if "검색" in h:
            ratio_idx = i

    if ratio_idx == -1:
        raise RuntimeError("검색비율 헤더 없음")

    name_idx = -1
    for i, h in enumerate(headers):
        if "종목명" in h:
            name_idx = i
            break

    rows, rank = [], 0
    stamp = now_kst().strftime("%Y-%m-%d %H:%M:%S")

    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue

        # 종목명
        nm = ""
        if 0 <= name_idx < len(tds):
            a = tds[name_idx].select_one("a")
            nm = (a.get_text(strip=True) if a else tds[name_idx].get_text(strip=True))
        else:
            for td in tds[:4]:
                a = td.select_one("a")
                if a and a.get_text(strip=True):
                    nm = a.get_text(strip=True)
                    break

        if not nm:
            continue

        # 검색비율 값
        if not (0 <= ratio_idx < len(tds)):
            continue
        ratio_txt = tds[ratio_idx].get_text(strip=True)
        score = _to_float2(ratio_txt)

        rank += 1
        rows.append({
            "rank": rank,
            "name": nm,
            "score": f"{score:.2f}",
            "ts": stamp
        })
        if rank >= 30:
            break

    return rows


# -------------------------------
# 2) 개별 스냅샷 CSV 저장
# -------------------------------
def save_snapshot_csv(rows: List[Dict]) -> str:
    ensure_data_dir()
    fn = f"data/naver_top_searchratio_{now_kst().strftime('%Y%m%d_%H%M')}.csv"
    with open(fn, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["rank", "name", "score", "ts"])
        w.writeheader()
        w.writerows(rows)

    print(f"✅ 스냅샷 저장: {fn}")

    # CSV는 3일만 유지
    cleanup_old_csv_files(days=3)
    return fn


# -------------------------------
# 3) 최근 12개 CSV 파일 목록
# -------------------------------
FNAME_RE = re.compile(r"naver_top_searchratio_(\d{8})_(\d{4})\.csv$")


def list_recent_snapshots(limit: int = 12) -> List[str]:
    ensure_data_dir()
    files = glob.glob("data/naver_top_searchratio_*.csv")

    def _key(fp: str) -> Tuple[str, str]:
        m = FNAME_RE.search(os.path.basename(fp))
        return (m.group(1), m.group(2)) if m else ("00000000", "0000")

    files_sorted = sorted(files, key=_key, reverse=True)
    return files_sorted[:limit]


# -------------------------------
# 4) 선택된 CSV 그룹에서 합계 점수 계산
# -------------------------------
def aggregate_scores_from_files(files: List[str]) -> Dict[str, float]:
    acc = defaultdict(float)
    for fp in files:
        with open(fp, "r", encoding="utf-8-sig") as f:
            rdr = csv.DictReader(f)
            for row in rdr:
                name = row.get("name", "").strip()
                try:
                    score = float(row.get("score", "0").replace(",", ""))
                except:
                    score = 0.0
                if name:
                    acc[name] += score
    return acc


# -------------------------------
# 5) 합계 Top30 → TXT 저장
# -------------------------------
def save_daily_top30_txt(score_map: Dict[str, float]) -> str:
    ensure_data_dir()
    today = now_kst().strftime("%Y%m%d")
    out_fn = f"data/daily_top30_{today}.txt"

    recent_files = list_recent_snapshots(limit=12)

    top = sorted(score_map.items(), key=lambda x: (-x[1], x[0]))[:30]

    lines = []
    lines.append(f"[네이버 인기검색 합계 Top30] (최근 12 스냅샷 기반)")
    lines.append(f"생성시각: {now_kst().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"스냅샷 수: {len(recent_files)}개")
    lines.append("-" * 48)
    for i, (name, total) in enumerate(top, 1):
        lines.append(f"{i:2d}. {name} | 합계: {total:.2f}")

    with open(out_fn, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(lines) + "\n")

    print(f"✅ 일일 Top30 저장: {out_fn}")

    cleanup_old_txt_files(days=14)
    return out_fn


# -------------------------------
# 메인 실행 부분
# -------------------------------
if __name__ == "__main__":
    rows = fetch_top30_search_ratio()
    save_snapshot_csv(rows)

    recent_files = list_recent_snapshots(limit=12)
    if not recent_files:
        print("⚠️ 최근 스냅샷이 없습니다.")
    else:
        score_map = aggregate_scores_from_files(recent_files)
        save_daily_top30_txt(score_map)
