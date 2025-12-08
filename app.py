import os
import csv
import time
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from bs4 import BeautifulSoup


def setup_driver():
    """Headless Chrome 설정"""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")

    return webdriver.Chrome(options=options)


def scrape_naver_top30():
    """네이버 인기종목(검색비율) Top 30 크롤링"""
    url = "https://finance.naver.com/sise/lastsearch2.naver"
    driver = setup_driver()

    print("[INFO] 네이버 인기검색종목 페이지 접속 중...")
    driver.get(url)

    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table.type_5"))
        )
    except:
        print("[ERROR] 페이지 로딩 실패")
        driver.quit()
        return []

    time.sleep(1)

    html = driver.page_source
    driver.quit()

    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.type_5")

    rows = table.select("tr")[2:]  # 상위 2줄은 헤더라서 제외
    results = []

    for row in rows:
        cols = row.select("td")

        if len(cols) < 5:
            continue

        rank = cols[0].get_text(strip=True)
        name = cols[1].get_text(strip=True)
        search_ratio = cols[2].get_text(strip=True)
        current_price = cols[3].get_text(strip=True)
        change_rate = cols[4].get_text(strip=True)

        if not rank.isdigit():
            continue  # 광고 등 노이즈 제거

        results.append([
            rank,
            name,
            search_ratio,
            current_price,
            change_rate
        ])

    print(f"[INFO] {len(results)}개 종목 수집 완료")
    return results


def save_csv(rows):
    """data 폴더에 CSV 저장"""
    os.makedirs("data", exist_ok=True)

    now = datetime.now().strftime("%Y-%m-%d_%H%M")
    filename = f"data/naver_top30_{now}.csv"

    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["순위", "종목명", "검색비율", "현재가", "등락률"])
        writer.writerows(rows)

    print(f"[INFO] 저장 완료 → {filename}")


def main():
    print("[INFO] 크롤링 시작")
    rows = scrape_naver_top30()

    if rows:
        save_csv(rows)
    else:
        print("[WARN] 저장할 데이터가 없음")

    print("[INFO] 작업 종료")


if __name__ == "__main__":
    main()
