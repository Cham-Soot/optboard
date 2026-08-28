#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
매일 장 마감 후 한 번 실행 — 거래 중인 월물의 행사가별 콜/풋 시세를 하루치 추가한다.

  python3 scripts/collect.py                 # 근월물 + 차월물
  python3 scripts/collect.py --all           # 거래 중인 월물 전부
  python3 scripts/collect.py --expiry 202609 # 특정 월물만

설정(config.json 또는 환경변수):
  STRIKE_MIN / STRIKE_MAX   수집할 행사가 범위 (비우면 전부)
  MONTHS                    near(근월물만) | near2(근월+차월, 기본) | all
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kis import Kis, KisError, kst_now, implied_index  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")


def load_config():
    cfg = {"STRIKE_MIN": None, "STRIKE_MAX": None, "MONTHS": "near2",
           "RANGE_MODE": "atm", "ATM_SPAN": 40,
           "PRODUCT": "KOSPI200 옵션"}
    p = os.path.join(ROOT, "config.json")
    if os.path.exists(p):
        cfg.update(json.load(open(p, encoding="utf-8")))
    for k in ("STRIKE_MIN", "STRIKE_MAX", "MONTHS", "RANGE_MODE", "ATM_SPAN"):
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    for k in ("STRIKE_MIN", "STRIKE_MAX"):
        cfg[k] = None if cfg[k] in (None, "", "null") else float(cfg[k])
    cfg["ATM_SPAN"] = int(cfg["ATM_SPAN"] or 40)
    cfg["RANGE_MODE"] = str(cfg["RANGE_MODE"] or "atm").lower()
    return cfg


def load_codes(yyyymm):
    """
    data/optcodes.json 에서 그 월물의 {행사가: {'c':코드,'p':코드}} 를 꺼낸다.
    (scripts/master.py 가 만들어 둔 거래소 종목마스터 캐시)
    """
    p = os.path.join(DATA, "optcodes.json")
    if not os.path.exists(p):
        return {}
    try:
        doc = json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}
    return {float(k): v for k, v in (doc.get("months", {}).get(yyyymm) or {}).items()}


def pick_strikes(all_strikes, center, cfg):
    """
    수집할 행사가를 고른다.

      RANGE_MODE = "atm"   지수를 따라 움직인다 — 등가 위아래로 ATM_SPAN 개씩 (권장)
                   "fixed" STRIKE_MIN ~ STRIKE_MAX 고정
                   "all"   가능한 것 전부
    """
    ks = sorted(all_strikes)
    mode = cfg["RANGE_MODE"]
    if mode == "fixed":
        lo, hi = cfg["STRIKE_MIN"], cfg["STRIKE_MAX"]
        return [s for s in ks
                if (lo is None or s >= lo) and (hi is None or s <= hi)]
    if mode != "atm" or center is None:
        return ks
    n = cfg["ATM_SPAN"]
    return [s for s in ks if s <= center][-n:] + [s for s in ks if s > center][:n]


def expiry_key(yyyymm):
    """202609 -> '2609'"""
    return yyyymm[2:6]


def doc_path(yyyymm):
    return os.path.join(DATA, expiry_key(yyyymm) + ".json")


def load_doc(yyyymm, product):
    p = doc_path(yyyymm)
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))
    return {"expiry": expiry_key(yyyymm),
            "label": "%s년 %s월물" % (yyyymm[2:4], int(yyyymm[4:6])),
            "product": product, "strikes": [], "dates": [],
            "updated": None, "rows": []}


def save_doc(doc):
    doc["strikes"] = sorted({float(s) for s in doc["strikes"]})
    doc["dates"] = sorted(set(doc["dates"]))
    doc["updated"] = kst_now().isoformat(timespec="seconds")
    doc["rows"].sort(key=lambda r: (r["date"], float(r["strike"])))
    os.makedirs(DATA, exist_ok=True)
    tmp = doc_path("20" + doc["expiry"]) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, doc_path("20" + doc["expiry"]))


def upsert(doc, date, strike, c, p):
    """같은 (날짜, 행사가)가 이미 있으면 덮어쓴다 — 하루에 여러 번 돌려도 안전."""
    for r in doc["rows"]:
        if r["date"] == date and float(r["strike"]) == strike:
            r["c"], r["p"] = c, p
            return False
    doc["rows"].append({"date": date, "strike": strike, "c": c, "p": p,
                        "memo1": "", "memo2": ""})
    if strike not in doc["strikes"]:
        doc["strikes"].append(strike)
    if date not in doc["dates"]:
        doc["dates"].append(date)
    return True


def collect_one(api, yyyymm, cfg, date):
    doc = load_doc(yyyymm, cfg["PRODUCT"])
    board, meta = api.callput_board(yyyymm)
    if not board:
        print("  [%s] 시세판이 비어 있습니다 (휴장이거나 월물이 아직 없음)" % yyyymm)
        return 0

    # 전광판은 100건 상한이라 등가 근처가 빠져 있을 수 있다.
    # 지수는 풋-콜 패리티로 정확히 역산되므로 그걸 기준으로 삼는다.
    center = implied_index(board) or meta.get("atm")
    codes = load_codes(yyyymm)
    ks_board = sorted(board)

    if codes:
        picked = pick_strikes(codes.keys(), center, cfg)
        src = "종목마스터"
    else:
        picked = pick_strikes(ks_board, center, cfg)
        src = "전광판만"
        if max(meta["n_call"], meta["n_put"]) >= 100:
            print("  [%s] ⚠ 전광판이 100건 상한(%g ~ %g)까지만 보냈고 종목마스터가 없습니다."
                  % (yyyymm, ks_board[0], ks_board[-1]))
            print("        python3 scripts/master.py 를 먼저 돌리면 등가 근처까지 받아옵니다.")

    if not picked:
        print("  [%s] 고를 행사가가 없습니다." % yyyymm)
        return 0
    need = [s for s in picked if s not in board]
    print("  [%s] 지수 %s · 행사가 %g ~ %g %d개 (%s, 개별조회 %d개)"
          % (yyyymm, center, picked[0], picked[-1], len(picked), src, len(need)))

    added = touched = 0
    for i, strike in enumerate(picked, 1):
        side = board.get(strike)
        if side is not None:                       # 전광판이 준 건 그대로 쓴다 (공짜)
            c, p = side.get("c", {}), side.get("p", {})
            cv = [c.get("open"), c.get("high"), c.get("low"), c.get("close")]
            pv = [p.get("open"), p.get("high"), p.get("low"), p.get("close")]
        else:                                      # 빠진 건 종목별로 하루치만 받아온다
            cv, pv = [None] * 4, [None] * 4
            for key, dest in (("c", "cv"), ("p", "pv")):
                code = (codes.get(strike) or {}).get(key)
                if not code:
                    continue
                try:
                    d8 = date.replace("-", "")
                    rows = api.daily_ohlc(code, d8, d8)
                except KisError:
                    rows = []
                if rows:
                    r = rows[-1]
                    v = [r["open"], r["high"], r["low"], r["close"]]
                    if dest == "cv":
                        cv = v
                    else:
                        pv = v
                time.sleep(0.15)
            if i % 20 == 0:
                print("        %d/%d …" % (i, len(picked)))
        if all(v is None for v in cv + pv):
            continue
        added += upsert(doc, date, strike, cv, pv)
        touched += 1

    save_doc(doc)
    print("  [%s] %s — 행사가 %d개 기록 (신규 %d)" % (yyyymm, date, touched, added))
    return touched


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expiry", help="특정 월물만 (예: 202609)")
    ap.add_argument("--all", action="store_true", help="거래 중인 월물 전부")
    ap.add_argument("--date", help="기록할 날짜 (기본: 오늘, KST)")
    args = ap.parse_args()

    cfg = load_config()
    now = kst_now()
    date = args.date or now.strftime("%Y-%m-%d")

    if now.weekday() >= 5 and not args.date:
        print("주말입니다 — 수집을 건너뜁니다.")
        return 0

    api = Kis()
    if args.expiry:
        targets = [args.expiry]
    else:
        ex = api.option_expiries()
        if not ex:
            print("월물 목록을 받지 못했습니다.")
            return 1
        targets = ex if (args.all or cfg["MONTHS"] == "all") \
            else ex[:1] if cfg["MONTHS"] == "near" else ex[:2]

    print("수집 대상: %s  (기록일 %s)" % (", ".join(targets), date))
    total = 0
    for i, ym in enumerate(targets):
        if i:
            time.sleep(1.2)          # 전광판 API는 1초 1회 이내 권장
        try:
            total += collect_one(api, ym, cfg, date)
        except KisError as e:
            print("  [%s] 실패: %s" % (ym, e))
    if total == 0:
        print("기록된 행사가가 없습니다 — 휴장일로 보입니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
