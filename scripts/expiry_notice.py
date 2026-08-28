#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
만기일이 가까워졌는지 판단해서 알림 문구를 만든다.

KOSPI200 지수옵션 최종거래일 = 각 결제월의 **두 번째 목요일**.
그 날이 휴장일이면 직전 개장일로 앞당겨진다. 휴장 여부는 `data/calendar.json`
(거래소 달력, calendar_sync.py 가 KIS 국내휴장일조회로 받아 둠)을 보고 판단하고,
달력이 없으면 두 번째 목요일을 그대로 쓴다.

  python3 scripts/expiry_notice.py            # 사람이 읽는 상태 출력
  python3 scripts/expiry_notice.py --github   # 알릴 게 있으면 제목/본문을 뱉고 종료코드 0
                                              # 알릴 게 없으면 종료코드 1
  python3 scripts/expiry_notice.py --json 18  # 앞으로 18개월치 만기일을 JSON 으로
"""
import argparse
import calendar
import datetime as dt
import json
import os
import sys

KST = dt.timezone(dt.timedelta(hours=9))
LEAD_DAYS = 3          # 만기 며칠 전부터 알릴지
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAL = os.path.join(ROOT, "data", "calendar.json")

_cal = None


def closed_days():
    """거래소가 문을 닫는 날 집합. 달력이 없으면 빈 집합(=주말만 피함)."""
    global _cal
    if _cal is None:
        try:
            _cal = set(json.load(open(CAL, encoding="utf-8")).get("closed", []))
        except Exception:
            _cal = set()
    return _cal


def calendar_covers(d):
    """그 날짜까지 달력이 실제로 확인해 준 구간인가."""
    try:
        c = json.load(open(CAL, encoding="utf-8"))
        return bool(c.get("to")) and dt.date.fromisoformat(c["to"]) >= d
    except Exception:
        return False


def second_thursday(year, month):
    """그 달의 두 번째 목요일."""
    first = dt.date(year, month, 1)
    offset = (calendar.THURSDAY - first.weekday()) % 7
    return first + dt.timedelta(days=offset + 7)


def expiry_of(year, month):
    """최종거래일 — 두 번째 목요일에서 시작해 휴장이면 직전 개장일까지 당긴다."""
    d = second_thursday(year, month)
    shut = closed_days()
    for _ in range(10):
        if d.weekday() < 5 and d.isoformat() not in shut:
            return d
        d -= dt.timedelta(days=1)
    return second_thursday(year, month)


def next_expiry(today=None):
    """오늘 기준으로 아직 지나지 않은 가장 가까운 만기일."""
    today = today or dt.datetime.now(KST).date()
    d = expiry_of(today.year, today.month)
    if d < today:
        y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        d = expiry_of(y, m)
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--github", action="store_true")
    ap.add_argument("--json", type=int, metavar="N",
                    help="앞뒤 N개월치 만기일을 JSON 으로 출력 (뷰어에 심는 용도)")
    ap.add_argument("--date", help="테스트용 기준일 YYYY-MM-DD")
    args = ap.parse_args()

    today = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(KST).date()

    if args.json:
        out, y, m = {}, today.year, today.month
        for i in range(-24, args.json):
            yy, mm = divmod((y * 12 + (m - 1)) + i, 12)
            d = expiry_of(yy, mm + 1)
            out["%s%02d" % (str(yy)[2:], mm + 1)] = d.isoformat()
        print(json.dumps(out, separators=(",", ":")))
        return 0

    exp = next_expiry(today)
    left = (exp - today).days
    ym = "%s년 %d월물" % (str(exp.year)[2:], exp.month)
    second = second_thursday(exp.year, exp.month)
    src = ("거래소 달력 확인됨" if calendar_covers(exp)
           else "달력 미확인 — 두 번째 목요일 기준")

    if not args.github:
        print("오늘 %s · 다음 만기 %s (%s) · D-%d · %s%s"
              % (today, exp, ym, left, src,
                 "  ※ 두 번째 목요일 %s 이 휴장이라 앞당겨짐" % second if exp != second else ""))
        return 0

    if left > LEAD_DAYS:
        return 1                                   # 아직 멀었다 — 알리지 않는다

    when = "오늘" if left == 0 else "D-%d" % left
    title = "[%s] 만기 %s — 마킹 보관하세요 (%s)" % (ym, when, exp)
    body = """**{ym}의 최종거래일은 {exp} (두 번째 목요일)입니다.** ({when})

만기가 지난 월물은 증권사 API로 **다시 받을 수 없습니다.** 만기 전후로 아래를 해 두세요.

1. 앱을 열고 이 월물이 마지막 거래일까지 들어왔는지 확인
2. 상단 **마킹 보관** → **marks.json 내려받기**
3. 내려받은 파일을 `data/marks.json` 에 덮어쓰고 커밋

이렇게 해 두면 다음 달 첫 자동 실행 때 `archive/` 에 시세·마킹·메모가 통째로 봉인됩니다.
마킹을 커밋하지 않으면 그 브라우저에만 남습니다.

> 날짜 근거: {src}{shift}
""".format(ym=ym, exp=exp, when=when, src=src,
           shift=("" if exp == second
                  else " — 두 번째 목요일 %s 이 휴장이라 %s 로 앞당겨졌습니다." % (second, exp)))

    print(title)
    print("---BODY---")
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
