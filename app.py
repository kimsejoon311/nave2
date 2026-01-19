import os
import re
import csv
import glob
import datetime as dt
from typing import List, Dict, Tuple
from collections import defaultdict

# Selenium 및 브라우저 설정
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
# 유틸리티 함수
# -------------------------------
def now_kst() -> dt.datetime:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))

def ensure_data_dir():
    os.makedirs("data", exist_ok=True)

def _to_float2(s: str) -> float:
    if not s: return 0.0
    m = re.findall(r"[0-9\.,]+", s)
    if not m: return 0.0
    v = m[0].replace(",", "")
    try: return round(float(v), 2)
    except: return 0.0

# -------------------------------
# 파일 관리 (정리)
# -------------------------------
def cleanup_old_csv_files(days: int = 3):
    ensure_data_dir()
    today = now_kst().date()
    pattern = re.compile(r"naver_top_searchratio_(\d{8})_(\d{4})\.csv$")
    for fp in glob.glob("data/naver_top_searchratio_*.csv"):
        m = pattern.search(os.path.basename(fp))
        if not m: continue
        try:
            file_date = dt.datetime.strptime(m.group(1), "%Y%m%d").date()
            if (today - file_date).days > days:
                os.remove(fp)
                print(f"🗑️ CSV 삭제됨: {fp}")
        except: continue

def cleanup_old_txt_files(days: int = 14):
    ensure_data_dir()
    today = now_kst().date()
    pattern = re.compile(r"daily_top30_(\d{8})\.txt$")
    for fp in glob.glob("data/daily_top30_*.txt"):
        m = pattern.search(os.path.basename(fp))
        if not m: continue
        try:
            file_date = dt.datetime.strptime(m.group(1), "%Y%m%d").date()
            if (today - file_date).days > days:
                os.remove(fp)
                print(f"🗑️ TXT 삭제됨: {fp}")
        except: continue

# -------------------------------
# 1) 인기종목 크롤링
# -------------------------------
def fetch_top30_search_ratio() -> List[Dict]:
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("user-agent=Mozilla/5.0")
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    base_url = "https://finance.naver.com/sise/lastsearch2.naver"
    driver.get(base_url)
    
    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.type_5")))
        soup = BeautifulSoup(driver.page_source, "html.parser")
    finally:
        driver.quit()

    table = soup.select_one("table.type_5")
    if not table: raise RuntimeError("데이터 테이블을 찾을 수 없습니다.")

    rows, rank = [], 0
    stamp = now_kst().strftime("%Y-%m-%d %H:%M:%S")

    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 5: continue
        
        nm_td = tr.select_one("a.tltle")
        if not nm_td: continue
        
        nm = nm_td.get_text(strip=True)
        # 검색비율은 보통 3번째 혹은 4번째 컬럼에 위치 (네이버 개편 대응용)
        ratio_txt = tds[2].get_text(strip=True) 
        score = _to_float2(ratio_txt)

        rank += 1
        rows.append({"rank": rank, "name": nm, "score": f"{score:.2f}", "ts": stamp})
        if rank >= 30: break
    return rows

# -------------------------------
# 2) 데이터 처리 및 비교 분석 (핵심 추가/수정)
# -------------------------------
def save_snapshot_csv(rows: List[Dict]) -> str:
    ensure_data_dir()
    fn = f"data/naver_top_searchratio_{now_kst().strftime('%Y%m%d_%H%M')}.csv"
    with open(fn, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["rank", "name", "score", "ts"])
        w.writeheader()
        w.writerows(rows)
    print(f"✅ 스냅샷 저장: {fn}")
    cleanup_old_csv_files(3)
    return fn

def list_recent_snapshots(limit: int = 12) -> List[str]:
    files = glob.glob("data/naver_top_searchratio_*.csv")
    return sorted(files, reverse=True)[:limit]

def aggregate_scores_from_files(files: List[str]) -> Dict[str, float]:
    acc = defaultdict(float)
    for fp in files:
        with open(fp, "r", encoding="utf-8-sig") as f:
            rdr = csv.DictReader(f)
            for row in rdr:
                acc[row["name"].strip()] += float(row.get("score", 0))
    return acc

def parse_past_txt(date_str: str) -> Dict[str, float]:
    """기존 TXT 파일에서 종목명과 점수 추출"""
    target_path = f"data/daily_top30_{date_str}.txt"
    past_scores = {}
    if not os.path.exists(target_path):
        return past_scores
    
    # 순위. 종목명 | 합계: 점수 패턴 추출
    pattern = re.compile(r"^\s*\d+\.\s+(.+?)\s*\|\s*합계:\s*([0-9\.]+)")
    with open(target_path, "r", encoding="utf-8-sig") as f:
        for line in f:
            match = pattern.search(line)
            if match:
                past_scores[match.group(1).strip()] = float(match.group(2))
    return past_scores

def save_daily_top30_txt(score_map: Dict[str, float]) -> str:
    ensure_data_dir()
    now = now_kst()
    today_str = now.strftime("%Y%m%d")
    out_fn = f"data/daily_top30_{today_str}.txt"

    # 과거 데이터(1~7일전) 불러오기
    past_comparison = {}
    for d in range(1, 8):
        d_str = (now - dt.timedelta(days=d)).strftime("%Y%m%d")
        past_comparison[d] = parse_past_txt(d_str)

    top = sorted(score_map.items(), key=lambda x: (-x[1], x[0]))[:30]
    
    lines = []
    lines.append(f"====================================================")
    lines.append(f" [네이버 인기검색 Top30 누적 분석] ")
    lines.append(f" 생성시간: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"====================================================\n")

    for i, (name, total) in enumerate(top, 1):
        lines.append(f"{i:2d}. {name} | 합계: {total:.2f}")
        
        # 등락 계산
        diff_str_list = []
        for day, past_scores in past_comparison.items():
            past_val = past_scores.get(name, 0)
            if past_val > 0:
                diff = ((total - past_val) / past_val) * 100
                sign = "▲" if diff > 0 else "▼" if diff < 0 else "-"
                diff_str_list.append(f"{day}일전:{sign}{abs(diff):.1f}%")
        
        if diff_str_list:
            lines.append(f"   └─ 등락폭: {' / '.join(diff_str_list)}")
        else:
            lines.append(f"   └─ 등락폭: (신규 진입 또는 과거 기록 없음)")
        
        lines.append("") # 가시성을 위한 한 줄 띄움

    with open(out_fn, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(lines))
    
    print(f"✅ 최종 리포트 생성 완료: {out_fn}")
    cleanup_old_txt_files(14)
    return out_fn

# -------------------------------
# 메인 실행부
# -------------------------------
if __name__ == "__main__":
    try:
        print("🚀 크롤링을 시작합니다...")
        rows = fetch_top30_search_ratio()
        save_snapshot_csv(rows)

        recent_files = list_recent_snapshots(limit=12)
        if not recent_files:
            print("⚠️ 분석할 스냅샷 CSV 파일이 부족합니다.")
        else:
            score_map = aggregate_scores_from_files(recent_files)
            save_daily_top30_txt(score_map)
            
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
