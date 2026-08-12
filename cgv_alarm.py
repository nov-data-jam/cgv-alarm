# -*- coding: utf-8 -*-
"""
CGV 예매 오픈 알리미 (GitHub Actions 버전)
- 영화마다 원하는 상영관을 따로 지정 가능.
- 이메일 정보는 GitHub Secrets에서 읽음.
- 이미 알린 회차는 seen.json에 기억 → 새로 열린 것만 알림.
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
# 설정
# ────────────────────────────────────────────────────────────────

# 기다릴 영화 + 그 영화에서 원하는 상영관 종류 (제목·상영관 모두 부분 매칭)
WATCHLIST = {
    "스파이더맨": ["4DX"],              # 스파이더맨은 4DX만
    "오디세이":   ["IMAX", "아이맥스"],  # 오디세이는 IMAX만
}

# 감시할 극장 (여기 극장에서 위 WATCHLIST를 전부 확인)
THEATERS = {
    "용산아이파크몰": "0013",
    "여의도":         "0112",
}

DAYS_AHEAD = 10

# 이메일 정보는 GitHub Secrets에서
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PW  = os.environ.get("GMAIL_APP_PW", "")
TO_ADDRESS    = os.environ.get("TO_ADDRESS", "")

SEEN_FILE = "seen.json"

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
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=0)


def send_email(subject, body):
    if not GMAIL_ADDRESS or not GMAIL_APP_PW or not TO_ADDRESS:
        print("[경고] 이메일 Secrets 미설정 — 메일 못 보냄.")
        return
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = f"CGV 알림봇 <{GMAIL_ADDRESS}>"
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
    params = {"coCd": CO_CD, "siteNo": site_no, "scnYmd": ymd, "rtctlScopCd": "08"}
    try:
        r = requests.get(API_URL, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        return r.json().get("data") or []
    except Exception as e:
        print(f"  [조회 실패] site={site_no} {ymd}: {e}")
        return []


def match_movie(item):
    title = str(item.get("movNm", ""))
    fmt   = str(item.get("expoScnsNm", "")) + " " + str(item.get("scnsNm", ""))
    for want_title, want_formats in WATCHLIST.items():
        if want_title in title and any(f in fmt for f in want_formats):
            return True
    return False


def main():
    seen = load_seen()
    first_run = (len(seen) == 0)
    today = datetime.date.today()
    new_hits = []

    for theater_name, site_no in THEATERS.items():
        for d in range(DAYS_AHEAD + 1):
            day = today + datetime.timedelta(days=d)
            ymd = day.strftime("%Y%m%d")
            for item in fetch_screenings(site_no, ymd):
                if not match_movie(item):
                    continue
                fmt_name = item.get("expoScnsNm") or item.get("scnsNm") or "특별관"
                mov = item.get("movNm")
                key = f"{site_no}|{ymd}|{fmt_name}|{mov}"
                if key in seen:
                    continue
                seen.add(key)
                new_hits.append((theater_name, mov, fmt_name, day))

    if first_run:
        print(f"[첫 실행] 현재 열린 회차 {len(new_hits)}건 저장 (메일 미발송).")
        save_seen(seen)
        return

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
