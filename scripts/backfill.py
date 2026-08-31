#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
과거 채우기 — 이미 지나간 날들을 한 번에 되메운다.
자동 수집을 시작한 날 이전 구간을 채울 때, 또는 하루 빠졌을 때 쓴다.

  python3 scripts/backfill.py --expiry 202609 --from 20260801 --to 20260826

동작: 해당 월물의 전광판에서 행사가별 종목코드를 얻은 뒤,
      종목코드마다 일별 OHLC(최대 100건)를 받아 채운다.
      행사가 하나당 콜·풋 2회 호출이라 60개 행사가면 약 120회 — 2~3분 걸린다.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kis import Kis, KisError  # noqa: E402
from collect import (load_config, load_doc, save_doc, upsert,
                     pick_strikes, load_codes, check_expiry)  # noqa: E402
from kis import implied_index  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expiry", required=True, help="월물 (예: 202609)")
    ap.add_argument("--from", dest="d1", required=True, help="시작일 YYYYMMDD")
    ap.add_argument("--to", dest="d2", required=True, help="종료일 YYYYMMDD")
    ap.add_argument("--sleep", type=float, default=0.3, help="호출 간격(초)")
    ap.add_argument("--reset", action="store_true",
                    help="이 월물의 기존 기록을 지우고 처음부터 다시 채운다 "
                         "(잘못된 행사가가 이미 들어간 경우)")
    args = ap.parse_args()

    cfg = load_config()
    args.expiry = check_expiry(args.expiry)
    api = Kis()
    board, meta = api.callput_board(args.expiry)
    if not board:
        print("전광판이 비어 있습니다 — 만기가 지난 월물은 조회되지 않습니다.")
        return 1

    center = implied_index(board) or meta.get("atm")
    codes = load_codes(args.expiry)
    universe = codes.keys() if codes else board.keys()
    strikes = pick_strikes(universe, center, cfg)
    print("지수 %s 기준 · 행사가 %g ~ %g · %s"
          % (center, strikes[0], strikes[-1],
             "종목마스터" if codes else "전광판만 (scripts/master.py 를 먼저 돌리세요)"))
    print("월물 %s · 행사가 %d개 · %s ~ %s" % (args.expiry, len(strikes), args.d1, args.d2))

    doc = load_doc(args.expiry, cfg["PRODUCT"])
    if args.reset and doc["rows"]:
        old = len(doc["rows"])
        doc["rows"], doc["strikes"], doc["dates"] = [], [], []
        print("기존 %d행을 비우고 다시 채웁니다." % old)
    merged = {}          # (date, strike) -> {'c':[...], 'p':[...]}

    for n, strike in enumerate(strikes, 1):
        for side in ("c", "p"):
            code = (codes.get(strike) or {}).get(side) \
                or ((board.get(strike) or {}).get(side) or {}).get("code")
            if not code:
                continue
            try:
                series = api.daily_ohlc(code, args.d1, args.d2)
            except KisError as e:
                print("  %s %s 실패: %s" % (strike, side, e))
                continue
            for row in series:
                slot = merged.setdefault((row["date"], strike),
                                         {"c": [None] * 4, "p": [None] * 4})
                slot[side] = [row["open"], row["high"], row["low"], row["close"]]
            time.sleep(args.sleep)
        print("  %3d/%d  행사가 %s" % (n, len(strikes), strike))

    added = 0
    for (date, strike), v in sorted(merged.items()):
        if all(x is None for x in v["c"] + v["p"]):
            continue
        added += upsert(doc, date, strike, v["c"], v["p"])
    save_doc(doc)
    print("완료 — %d행 신규, 총 %d행 / 거래일 %d일" % (added, len(doc["rows"]), len(doc["dates"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
