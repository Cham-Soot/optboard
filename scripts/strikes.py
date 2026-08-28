#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
행사가 진단 — 증권사가 실제로 어떤 행사가를 돌려주는지 그대로 보여 준다.

  python3 scripts/strikes.py              # 근월물
  python3 scripts/strikes.py --expiry 202609
  python3 scripts/strikes.py --all        # 거래 중인 월물 전부

전광판 API는 콜·풋 **각 100건**이 상한이다. 상한에 걸리면 어느 쪽이 잘렸는지 짚어 준다.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kis import Kis, KisError, implied_index  # noqa: E402


def fmt(s):
    return ("%g" % s) if s % 1 else str(int(s))


def report(api, ym):
    board, meta = api.callput_board(ym)
    if not board:
        print("  [%s] 비어 있습니다." % ym)
        return
    ks = sorted(board)
    idx, atm = implied_index(board), meta["atm"]
    step = min((round(b - a, 4) for a, b in zip(ks, ks[1:])), default=0)

    print("\n" + "=" * 60)
    print(" 월물 %s" % ym)
    print("=" * 60)
    print("  역산 지수(풋-콜)   : %s   ← 행사가+콜종가-풋종가" % (idx if idx else "(계산 불가)"))
    print("  전광판 ATM 표시    : %s" % (fmt(atm) if atm else "(없음)"))
    print("  받은 행사가 개수   : 콜 %d개 · 풋 %d개" % (meta["n_call"], meta["n_put"]))
    print("  행사가 범위        : %s ~ %s   (간격 %s)"
          % (fmt(ks[0]), fmt(ks[-1]), fmt(step) if step else "?"))

    center = idx or atm
    if center:
        below = [s for s in ks if s < center]
        above = [s for s in ks if s > center]
        print("  기준(%s) 아래      : %d개%s" % (fmt(center), len(below),
              "   ← 이쪽이 부족합니다" if len(below) < 10 else ""))
        print("  기준(%s) 위        : %d개%s" % (fmt(center), len(above),
              "   ← 이쪽이 부족합니다" if len(above) < 10 else ""))

    # 종목마스터가 있으면 원래 몇 개인지 대조해 준다
    try:
        from collect import load_codes
        full = sorted(load_codes(ym))
    except Exception:
        full = []
    if full:
        print("  종목마스터 기준    : 행사가 %d개 (%s ~ %s)" % (len(full), fmt(full[0]), fmt(full[-1])))

    hit = max(meta["n_call"], meta["n_put"]) >= 100
    print("\n  판정:", end=" ")
    if hit and center and ks[0] > center:
        print("잘렸습니다. 100건 상한에 걸려 **높은 행사가 쪽만** 받았습니다.")
        print("        지금 보이는 %s 부터는 전부 기준가 위쪽이라 쓸모가 적습니다." % fmt(ks[0]))
    elif hit and center and ks[-1] < center:
        print("잘렸습니다. 100건 상한에 걸려 **낮은 행사가 쪽만** 받았습니다.")
    elif hit:
        print("100건 상한에 걸렸습니다. 양 끝이 잘렸을 수 있습니다.")
    else:
        print("상한에 걸리지 않았습니다. 이게 거래소가 내주는 전부입니다.")
    if hit:
        print("        → scripts/master.py 를 돌려 두면 종목마스터로 등가 근처까지 받아옵니다."
              if not full else
              "        → 종목마스터가 있으므로 collect.py 는 등가 근처까지 채웁니다.")

    print("\n  받은 행사가 (처음 8개 / 마지막 8개):")
    print("    앞 : " + ", ".join(fmt(s) for s in ks[:8]))
    print("    뒤 : " + ", ".join(fmt(s) for s in ks[-8:]))

    if center:
        near = sorted(ks, key=lambda s: abs(s - center))[:5]
        print("\n  기준가에 가장 가까운 행사가 5개: " + ", ".join(fmt(s) for s in sorted(near)))
        for s in sorted(near)[:3]:
            c = (board[s].get("c") or {}).get("close")
            p = (board[s].get("p") or {}).get("close")
            print("    %8s  콜 종가 %-8s 풋 종가 %s" % (fmt(s), c, p))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expiry")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    api = Kis()
    if args.expiry:
        targets = [args.expiry]
    else:
        ex = api.option_expiries()
        print("거래 중인 월물: " + ", ".join(ex))
        targets = ex if args.all else ex[:1]

    import time
    for i, ym in enumerate(targets):
        if i:
            time.sleep(1.2)
        try:
            report(api, ym)
        except KisError as e:
            print("  [%s] 실패: %s" % (ym, e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
