import os
import re
import csv
import glob
import datetime as dt
from typing import List, Dict, Tuple
from collections import defaultdict

# ... (기존 import 및 유틸 함수 fetch_top30_search_ratio 등은 동일하게 유지) ...

# -------------------------------
# 추가: 과거 TXT 파일에서 점수 파싱
# -------------------------------
def parse_past_txt(date_str: str) -> Dict[str, float]:
    """'daily_top30_20231027.txt' 파일에서 {종목명: 점수} 딕셔너리 추출"""
    target_path = f"data/daily_top30_{date_str}.txt"
    past_scores = {}
    if not os.path.exists(target_path):
        return past_scores

    # 정규식: "순위. 종목명 | 합계: 점수" 패턴 매칭
    pattern = re.compile(r"^\s*\d+\.\s+(.+?)\s*\|\s*합계:\s*([0-9\.]+)")
    
    with open(target_path, "r", encoding="utf-8-sig") as f:
        for line in f:
            match = pattern.search(line)
            if match:
                name = match.group(1).strip()
                score = float(match.group(2))
                past_scores[name] = score
    return past_scores

def get_change_str(current: float, past: float) -> str:
    """등락폭 계산 및 기호 표시"""
    if past == 0: return "(-)"
    diff_percent = ((current - past) / past) * 100
    
    if diff_percent > 0:
        return f"▲{diff_percent:+.1f}%"
    elif diff_percent < 0:
        return f"▼{diff_percent:+.1f}%"
    else:
        return "(-)"

# -------------------------------
# 5) 합계 Top30 → TXT 저장 (수정됨)
# -------------------------------
def save_daily_top30_txt(score_map: Dict[str, float]) -> str:
    ensure_data_dir()
    now = now_kst()
    today_str = now.strftime("%Y%m%d")
    out_fn = f"data/daily_top30_{today_str}.txt"

    # 1. 과거 데이터 로드 (1일 전 ~ 7일 전)
    past_data_map = {}
    for d in range(1, 8):
        target_date = (now - dt.timedelta(days=d)).strftime("%Y%m%d")
        past_data_map[d] = parse_past_txt(target_date)

    recent_files = list_recent_snapshots(limit=12)
    top = sorted(score_map.items(), key=lambda x: (-x[1], x[0]))[:30]

    lines = []
    lines.append(f"================================================")
    lines.append(f"[네이버 인기검색 합계 Top30 - 등락 분석]")
    lines.append(f"생성시각: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"참조 스냅샷: {len(recent_files)}개")
    lines.append(f"================================================\n")

    for i, (name, total) in enumerate(top, 1):
        # 현재 정보
        row_str = f"{i:2d}. {name} | 합계: {total:.2f}\n"
        
        # 대비 정보 (1일전, 3일전, 7일전 등 주요 지표만 표시하거나 모두 표시)
        changes = []
        for day, scores in past_data_map.items():
            past_val = scores.get(name, 0)
            if past_val > 0:
                changes.append(f"{day}일전:{get_change_str(total, past_val)}")
        
        if changes:
            row_str += f"    └─ 비교: {' / '.join(changes)}\n"
        else:
            row_str += f"    └─ 비교: (과거 기록 없음)\n"
        
        lines.append(row_str) # 종목 간 가시성을 위해 내부에 \n 포함

    with open(out_fn, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(lines) + "\n")

    print(f"✅ 일일 Top30(등락폭 포함) 저장 완료: {out_fn}")
    cleanup_old_txt_files(days=14)
    return out_fn

# (이후 메인 실행 부분은 기존과 동일)
