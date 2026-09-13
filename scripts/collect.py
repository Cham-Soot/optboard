#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verified daily prices. Exit: 0 complete/closed, 2 config, 3 retryable, 4 incomplete."""
import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kis import Kis, KisError, kst_now
from public_data import assert_public, atomic_json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
COMPLETE = {"ok", "no_trade"}


class CollectionIncomplete(KisError):
    pass


def load_config():
    cfg = {"STRIKE_MIN": None, "STRIKE_MAX": None, "MONTHS": "near2",
           "RANGE_MODE": "atm", "ATM_SPAN": 40, "PRODUCT": "KOSPI200 옵션"}
    path = Path(ROOT) / "config.json"
    if path.exists():
        cfg.update(json.loads(path.read_text(encoding="utf-8")))
    for key in ("STRIKE_MIN", "STRIKE_MAX", "MONTHS", "RANGE_MODE", "ATM_SPAN"):
        if os.environ.get(key):
            cfg[key] = os.environ[key]
    for key in ("STRIKE_MIN", "STRIKE_MAX"):
        cfg[key] = None if cfg[key] in (None, "", "null") else float(cfg[key])
    cfg["ATM_SPAN"] = int(cfg["ATM_SPAN"])
    if not 1 <= cfg["ATM_SPAN"] <= 600 or cfg["RANGE_MODE"] not in ("atm", "fixed", "all"):
        raise ValueError("행사가 범위 설정을 확인하세요")
    if cfg["MONTHS"] not in ("near", "near2", "all"):
        raise ValueError("MONTHS는 near, near2, all 중 하나여야 합니다")
    return cfg


def load_codes(yyyymm):
    path = Path(DATA) / "optcodes.json"
    if not path.exists():
        return {}
    obj = json.loads(path.read_text(encoding="utf-8"))
    return {float(k): v for k, v in obj.get("months", {}).get(yyyymm, {}).items()}


def pick_strikes(all_strikes, center, cfg):
    ks = sorted(set(all_strikes))
    if cfg["RANGE_MODE"] == "fixed":
        lo, hi = cfg["STRIKE_MIN"], cfg["STRIKE_MAX"]
        return [s for s in ks if (lo is None or s >= lo) and (hi is None or s <= hi)]
    if cfg["RANGE_MODE"] == "all":
        return ks
    if center is None or not math.isfinite(center) or center <= 0:
        raise ValueError("해당 거래일의 KOSPI200 지수가 없어 ATM 범위를 정할 수 없습니다")
    n = cfg["ATM_SPAN"]
    return [s for s in ks if s <= center][-n:] + [s for s in ks if s > center][:n]


def check_expiry(value):
    value = (value or "").strip()
    if len(value) == 6 and value.isdigit() and 2000 <= int(value[:4]) <= 2099 and "01" <= value[4:] <= "12":
        return value
    raise ValueError("월물은 YYYYMM 6자리입니다. 예: 202609 (날짜는 --date 2026-08-28)")


def expiry_key(yyyymm):
    return yyyymm[2:6]


def doc_path(yyyymm):
    return os.path.join(DATA, expiry_key(yyyymm) + ".json")


def load_doc(yyyymm, product):
    path = Path(doc_path(yyyymm))
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"expiry": expiry_key(yyyymm), "label": "%s년 %s월물" % (yyyymm[2:4], int(yyyymm[4:])),
            "product": product, "strikes": [], "dates": [], "updated": None, "rows": []}


def save_doc(doc):
    doc["strikes"] = sorted(set(float(s) for s in doc["strikes"]))
    doc["dates"] = sorted(set(doc["dates"]))
    doc["updated"] = kst_now().isoformat(timespec="seconds")
    doc["rows"].sort(key=lambda r: (r["date"], float(r["strike"])))
    assert_public(doc, doc["expiry"])
    atomic_json(doc_path("20" + doc["expiry"]), doc)


def upsert(doc, date, strike, c, p):
    """Missing/failed responses never replace a previously successful side."""
    for row in doc["rows"]:
        if row["date"] == date and float(row["strike"]) == strike:
            for side, values in (("c", c), ("p", p)):
                if values is not None and any(v is not None for v in values):
                    row[side] = list(values)
            return False
    doc["rows"].append({"date": date, "strike": strike,
                        "c": list(c) if c is not None else [None] * 4,
                        "p": list(p) if p is not None else [None] * 4})
    if strike not in doc["strikes"]:
        doc["strikes"].append(strike)
    if date not in doc["dates"]:
        doc["dates"].append(date)
    return True


def calendar_data():
    obj = json.loads((Path(DATA) / "calendar.json").read_text(encoding="utf-8"))
    if not obj.get("from") or not obj.get("to"):
        raise ValueError("거래일 달력을 먼저 갱신해야 합니다")
    return obj


def open_day(day, cal):
    d = dt.date.fromisoformat(day)
    if not cal["from"] <= day <= cal["to"]:
        raise ValueError("달력이 확인되지 않은 날짜입니다: " + day)
    return d.weekday() < 5 and day not in set(cal.get("closed", []))


def recent_open_days(days=7, end=None):
    cal = calendar_data()
    today = dt.date.fromisoformat(end) if end else kst_now().date()
    out = []
    for i in range(1, days + 1):
        d = (today - dt.timedelta(days=i)).isoformat()
        if d >= cal["from"] and open_day(d, cal):
            out.append(d)
    return sorted(out)


def quote_values(row):
    values = [row.get(k) for k in ("open", "high", "low", "close")]
    if any(v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))
                              or not math.isfinite(v) or v < 0) for v in values):
        raise ValueError("잘못된 가격 값")
    if row.get("volume") == 0:
        return None, "no_trade"
    if any(v is None for v in values):
        raise ValueError("거래 시세의 OHLC 일부 누락")
    op, high, low, close = values
    if not low <= min(op, close) <= max(op, close) <= high:
        raise ValueError("시가·고가·저가·종가 관계 불일치")
    return values, "ok"


def collect_range(api, yyyymm, cfg, dates, repair_only=False):
    """Query each needed contract once for its entire required date range."""
    dates = sorted(set(dates))
    if not dates:
        return 0
    codes = load_codes(yyyymm)
    if not codes:
        raise CollectionIncomplete("%s 종목마스터가 없습니다. 잘린 전광판으로 대체하지 않습니다." % yyyymm)
    doc = load_doc(yyyymm, cfg["PRODUCT"])
    states = doc.setdefault("collection", {})
    unplanned = [day for day in dates if not states.get(day, {}).get("expected")]
    indices = api.index_ohlc(min(unplanned), max(unplanned)) if unplanned and cfg["RANGE_MODE"] == "atm" else {}
    needed, failures, retryable, touched = {}, [], False, 0
    checked = kst_now().isoformat(timespec="seconds")
    for day in dates:
        state = states.setdefault(day, {"contracts": {}})
        if not state.get("expected"):
            center = indices.get(day)
            try:
                picked = pick_strikes(codes, center, cfg)
                if not picked:
                    raise ValueError("수집할 행사가가 없습니다")
            except ValueError as exc:
                state.update(status="incomplete", checked=checked, error=str(exc))
                failures.append(day + ": " + str(exc))
                continue
            expected = {"%g|%s" % (strike, side): {"strike": strike, "side": side,
                         "code": codes[strike].get(side)} for strike in picked for side in ("c", "p")}
            state.update(expected=expected, center=center, index_source="KIS KOSPI200 daily" if center else "configured range")
        for identity, contract in state["expected"].items():
            previous = state.setdefault("contracts", {}).get(identity, {})
            if repair_only and previous.get("status") in COMPLETE:
                continue
            code = contract.get("code")
            if not code:
                code = codes.get(float(contract["strike"]), {}).get(contract["side"])
                if code:
                    contract["code"] = code
            if not code:
                state["contracts"][identity] = {"status": "missing_code", "checked": checked}
                failures.append(day + ": 종목코드 누락")
                continue
            needed.setdefault(code, []).append((day, identity, contract))

    for code, targets in needed.items():
        start, end = min(t[0] for t in targets), max(t[0] for t in targets)
        error, rows = None, {}
        try:
            series = api.daily_ohlc(code, start.replace("-", ""), end.replace("-", ""))
            for row in series:
                day = row.get("date", "")
                if start <= day <= end:
                    if day in rows and rows[day] != row:
                        raise ValueError("같은 거래일에 상충하는 응답")
                    rows[day] = row
        except (KisError, ValueError) as exc:
            error = str(exc)
            retryable = retryable or getattr(exc, "retryable", False)
        for day, identity, contract in targets:
            state = states[day]
            status, values = "missing", None
            message = error
            if not message and day in rows:
                try:
                    values, status = quote_values(rows[day])
                except ValueError as exc:
                    message, status = str(exc), "invalid"
            elif message:
                status = "error"
            else:
                message = "요청 거래일의 응답이 없습니다"
            item = {"status": status, "checked": checked}
            if message:
                item["error"] = message[:200]
                failures.append("%s %s: %s" % (day, identity, message))
            state["contracts"][identity] = item
            if status in COMPLETE:
                upsert(doc, day, contract["strike"], values if contract["side"] == "c" else None,
                       values if contract["side"] == "p" else None)
                touched += 1
        time.sleep(0.15)

    for day in dates:
        state = states[day]
        expected = state.get("expected", {})
        successful = sum(state.get("contracts", {}).get(k, {}).get("status") in COMPLETE for k in expected)
        state.update(checked=checked, expected_count=len(expected), complete_count=successful,
                     status="complete" if expected and successful == len(expected) else "incomplete")
        print("  [%s] %s: %d/%d 종목 확인 (%s)" % (yyyymm, day, successful, len(expected), state["status"]))
    save_doc(doc)
    if failures or any(states[d]["status"] != "complete" for d in dates):
        raise CollectionIncomplete("%s: 미완료 %d건. 성공한 값은 보존했습니다. %s" %
                                   (yyyymm, len(failures), "; ".join(failures[:3])), retryable=retryable)
    return touched


def collect_one(api, yyyymm, cfg, date, use_board=False):
    # Compatible argument, but current quotes are never used, even with True.
    return collect_range(api, yyyymm, cfg, [date])


def heal_missing(api, targets, cfg, today):
    errors = []
    for ym in targets:
        doc = load_doc(ym, cfg["PRODUCT"])
        if not doc.get("dates"):
            continue
        first = min(doc["dates"])
        days = [day for day in recent_open_days(7, today) if day >= first
                and doc.get("collection", {}).get(day, {}).get("status") != "complete"]
        try:
            collect_range(api, ym, cfg, days, repair_only=True)
        except KisError as exc:
            errors.append(exc)
    if errors:
        raise CollectionIncomplete("누락 복구 미완료: " + "; ".join(str(e) for e in errors),
                                   retryable=any(getattr(e, "retryable", False) for e in errors))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expiry", help="월물 YYYYMM")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--date", help="실제 거래일 YYYY-MM-DD")
    ap.add_argument("--force", action="store_true", help="장 마감 시각 검사만 생략")
    args = ap.parse_args()
    report = {"checked": kst_now().isoformat(timespec="seconds"), "status": "failed", "errors": []}
    try:
        ym_arg = check_expiry(args.expiry) if args.expiry else None
        cfg, cal, now = load_config(), calendar_data(), kst_now()
        day = dt.date.fromisoformat(args.date) if args.date else now.date()
        if day > now.date():
            raise ValueError("미래 날짜는 수집할 수 없습니다")
        report["date"] = day.isoformat()
        if not open_day(day.isoformat(), cal):
            if args.date:
                raise ValueError("지정한 날짜는 거래일이 아닙니다")
            report["status"] = "closed"
            return 0
        if day == now.date() and now.hour < 16 and not args.force:
            raise ValueError("정규장 종가 수집은 16시 이후 실행하세요")
        if str(cal.get("updated", ""))[:10] != now.date().isoformat():
            raise ValueError("오늘의 휴장일 확인이 필요합니다. calendar_sync.py를 먼저 실행하세요")
        api = Kis()
        expiries = [ym_arg] if ym_arg else api.option_expiries()
        targets = expiries if ym_arg or args.all or cfg["MONTHS"] == "all" else expiries[:1 if cfg["MONTHS"] == "near" else 2]
        if not targets:
            raise KisError("월물 목록이 없습니다", retryable=True)
        errors = []
        for ym in targets:
            try:
                collect_one(api, ym, cfg, day.isoformat())
            except KisError as exc:
                errors.append(exc)
        if not args.date and not ym_arg:
            try:
                heal_missing(api, targets, cfg, day.isoformat())
            except KisError as exc:
                errors.append(exc)
        report["targets"] = targets
        if errors:
            report["errors"] = [str(e)[:600] for e in errors]
            report["status"] = "incomplete"
            return 3 if any(getattr(e, "retryable", False) for e in errors) else 4
        report["status"] = "complete"
        return 0
    except (ValueError, FileNotFoundError) as exc:
        report["errors"] = [str(exc)]
        return 2
    except KisError as exc:
        report["errors"] = [str(exc)[:600]]
        return 3 if getattr(exc, "retryable", False) else 4
    finally:
        atomic_json(Path(DATA) / "collection_status.json", report)
        print("수집 상태: " + report["status"])
        for message in report["errors"]:
            print(message)


if __name__ == "__main__":
    sys.exit(main())
