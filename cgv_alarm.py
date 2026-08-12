# -*- coding: utf-8 -*-
"""
CGV 예매 오픈 알리미 (GitHub Actions 버전)
- 용산아이파크몰 / 여의도에서 특정 영화가 4DX·IMAX로 열리면 이메일 알림.
- GitHub Actions가 5분마다 이 파일을 실행한다.
- 이메일 정보는 코드에 적지 않고 GitHub Secrets(비밀 금고)에서 읽는다.
- 이미 알린 회차는 seen.json 파일에 기억해서, 새로 열린 것만 알린다.
  (그래서 처음 켤 때 메일이 쏟아지지 않는다.)
"""

import os
import json
import datetime
import smtplib
import ssl
from email.mime.text import MIMEText
from email.header import Header
import requests

# ────────────────────────────────────────────────────────────────
# 설정 — 여기서 바꿀 건 영화 제목/극장 정도. 이메일은 Secrets로 들어옴.
# ────────────────────────────────────────────────────────────────

# 기다릴 영화 제목 (movNm에 이 글자가 들어가면 매칭). 다른 영화 기다릴 땐 이 줄만 수정.
TARGET_TITLE = "스파이더맨"

# 감시할 극장 + 각 극장에서 원하는 상영관 종류
THEATERS = {
    "용산아이파크몰": {"siteNo": "0013", "formats": ["4DX", "아이맥스", "IMAX"]},
    "여의도":         {"siteNo": "0112", "formats": ["4DX"]},
}

# 오늘부터 며칠 뒤까지 살펴볼지
DAYS_AHEAD = 10

# 이메일 정보는 GitHub Secrets에서 읽어온다 (코드에 직접 안 적음)
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PW  = os.environ.get("GMAIL_APP_PW", "")
TO_ADDRESS    = os.environ.get("TO_ADDRESS", "")

# 이미 알린 회차를 기억하는 파일
SEEN_FILE = "seen.json"

# ────────────────────────────────────────────────────────────────
# 여기서부터는 건드릴 필요 없음
# ────────────────────────────────────────────────────────────────

CO_CD = "A420"
API_URL = "https://cgv.co.kr/api/v1/booking/searchMovScnInfo"

HEADERS = {
    "accept": "application/json",
    "accept-language": "ko-KR",
    "referer": "https://cgv.co.kr/cnm/movieBook/cinema",
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/151.0.0.0 Safari/537.36"),
}


def load_seen():
    """이전에 알린 회차 목록을 파일에서 불러온다."""
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()  # 파일 없으면(=첫 실행) 빈 목록


def save_seen(seen):
    """알린 회차 목록을 파일에 저장한다."""
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=0)


def send_email(subject, body):
    """지메일 SMTP로 메일 전송."""
    if not GMAIL_ADDRESS or not GMAIL_APP_PW or not TO_ADDRESS:
        print("[경고] 이메일 Secrets가 설정되지 않음 — 메일을 보내지 못합니다.")
        return
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = GMAIL_ADDRESS
        msg["To"] = TO_ADDRESS
        pw = GMAIL_APP_PW.replace(" ", "")
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
            server.login(GMAIL_ADDRESS, pw)
            server.sendmail(GMAIL_ADDRESS, [TO_ADDRESS], msg.as_string())
        print("  → 이메일 전송 완료:", subject)
    except Exception as e:
        print("[이메일 전송 실패]", e)


def fetch_screenings(site_no, ymd):
    """한 극장·하루치 상영 정보를 CGV에서 가져온다."""
    params = {"coCd": CO_CD, "siteNo": site_no, "scnYmd": ymd, "rtctlScopCd": "08"}
    try:
        r = requests.get(API_URL, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        return r.json().get("data") or []
    except Exception as e:
        print(f"  [조회 실패] site={site_no} {ymd}: {e}")
        return []


def matches(item, wanted_formats):
    title = str(item.get("movNm", ""))
    fmt   = str(item.get("expoScnsNm", "")) + " " + str(item.get("scnsNm", ""))
    if TARGET_TITLE not in title:
        return False
    return any(f in fmt for f in wanted_formats)


def main():
    seen = load_seen()
    first_run = (len(seen) == 0)  # 기억 파일이 비었으면 첫 실행
    today = datetime.date.today()
    new_hits = []

    for theater_name, info in THEATERS.items():
        site_no = info["siteNo"]
        formats = info["formats"]
        for d in range(DAYS_AHEAD + 1):
            day = today + datetime.timedelta(days=d)
            ymd = day.strftime("%Y%m%d")
            for item in fetch_screenings(site_no, ymd):
                if not matches(item, formats):
                    continue
                fmt_name = item.get("expoScnsNm") or item.get("scnsNm") or "특별관"
                key = f"{site_no}|{ymd}|{fmt_name}|{item.get('movNm')}"
                if key in seen:
                    continue
                seen.add(key)
                new_hits.append((theater_name, item.get("movNm"), fmt_name, day))

    # 첫 실행이면: 지금 열려 있는 건 '이미 아는 것'으로만 기록하고 메일은 안 보냄
    if first_run:
        print(f"[첫 실행] 현재 열린 회차 {len(new_hits)}건을 기준으로 저장 (메일 미발송).")
        save_seen(seen)
        return

    # 두 번째 실행부터: 새로 생긴 것만 메일 발송
    if new_hits:
        for theater_name, mov, fmt_name, day in new_hits:
            subject = f"[CGV] {theater_name} {mov} {fmt_name} 예매 열림!"
            body = (f"CGV 예매가 열렸습니다.\n\n"
                    f"극장: {theater_name}\n영화: {mov}\n상영관: {fmt_name}\n"
                    f"날짜: {day.strftime('%Y-%m-%d')}\n\n"
                    f"예매: https://cgv.co.kr/cnm/movieBook/cinema")
            send_email(subject, body)
    else:
        print("새로 열린 회차 없음.")

    save_seen(seen)


if __name__ == "__main__":
    main()
