#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
한국거래소 개장 달력을 받아 data/calendar.json 에 캐시한다.

출처는 한국투자증권 오픈API의 **국내휴장일조회(CTCA0903R)** 다.
거래소 자신의 달력이라 주말·공휴일·근로자의날(5/1)·연말 폐장·임시 휴장이 모두 반영돼 있다.
이미 쓰고 있는 앱키를 그대로 쓰므로 API 키를 새로 받을 필요가 없다.

KIS 안내에 따라 **하루 한 번**만 호출한다. 캐시가 6개월 앞을 덮고 있으면 건너뛴다.

  python3 scripts/calendar_sync.py          # 필요할 때만 갱신
  python3 scripts/calendar_sync.py --force  # 무조건 다시 받기
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kis import Kis, KisError, kst_now  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "data", "calendar.json")
HORIZON = 150          # 앞으로 이만큼(일)은 덮고 있어야 한다


def load():
    if os.path.exists(PATH):
        try:
            return json.load(open(PATH, encoding="utf-8"))
        except Exception:
            pass
    return {"closed": [], "from": None, "to": None, "updated": None,
            "source": "KIS 국내휴장일조회 (CTCA0903R)"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    cal = load()
    today = kst_now().date()

    if not args.force and cal.get("to"):
        if dt.date.fromisoformat(cal["to"]) >= today + dt.timedelta(days=HORIZON):
            print("달력이 %s 까지 있습니다 — 갱신하지 않습니다." % cal["to"])
            return 0

    try:
        api = Kis()
        closed, last = api.closed_days(today.strftime("%Y%m%d"))
    except KisError as e:
        print("달력을 받지 못했습니다: %s" % e)
        print("(만기일은 '두 번째 목요일' 기준으로만 계산됩니다)")
        return 0                     # 수집 자체를 막지는 않는다

    if not closed and not last:
        print("휴장일 응답이 비어 있습니다 — 이전 달력을 그대로 둡니다.")
        return 0

    keep = [d for d in cal.get("closed", []) if d < today.isoformat()]
    cal["closed"] = sorted(set(keep + closed))
    cal["from"] = cal.get("from") or (cal["closed"][0] if cal["closed"] else today.isoformat())
    cal["to"] = last or cal.get("to")
    cal["updated"] = kst_now().isoformat(timespec="seconds")

    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    json.dump(cal, open(PATH, "w", encoding="utf-8"), ensure_ascii=False)
    upcoming = [d for d in cal["closed"] if d >= today.isoformat()][:6]
    print("달력 갱신 — %s 까지, 휴장일 %d일. 다가오는 휴장: %s"
          % (cal["to"], len(cal["closed"]), ", ".join(upcoming) or "없음"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
