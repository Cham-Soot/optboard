#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backfill dated quotations; a reset is staged and backed up before replacement."""
import argparse
import datetime as dt
from pathlib import Path
import shutil
import sys
import tempfile

import collect
from kis import Kis, KisError, kst_now


def run(api, ym, cfg, start, end, reset=False):
    # Historical index observations establish trading dates even before our calendar cache.
    days = sorted(api.index_ohlc(start.isoformat(), end.isoformat()))
    if not days:
        raise collect.CollectionIncomplete("지정 구간의 거래일을 확인하지 못했습니다")
    if not reset:
        return collect.collect_range(api, ym, cfg, days)
    original_data = collect.DATA
    original = Path(collect.doc_path(ym))
    private = Path(collect.ROOT) / ".private" / "backfill"
    private.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=private) as staging:
        shutil.copyfile(Path(original_data) / "optcodes.json", Path(staging) / "optcodes.json")
        try:
            collect.DATA = staging
            result = collect.collect_range(api, ym, cfg, days)
            replacement = collect.load_doc(ym, cfg["PRODUCT"])
        finally:
            collect.DATA = original_data
        # An incomplete staged collection raises above, leaving the original untouched.
        if original.exists():
            backup = private / (kst_now().strftime("%Y%m%d-%H%M%S-%f") + "-" + original.name)
            shutil.copyfile(original, backup)
            print("교체 전 원본 백업: " + str(backup))
        collect.save_doc(replacement)
        return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expiry", required=True)
    ap.add_argument("--from", dest="start", required=True, help="YYYYMMDD")
    ap.add_argument("--to", dest="end", required=True, help="YYYYMMDD")
    ap.add_argument("--reset", action="store_true", help="전체 성공할 때만 원본을 백업하고 지정 구간으로 교체")
    args = ap.parse_args()
    try:
        ym = collect.check_expiry(args.expiry)
        start = dt.datetime.strptime(args.start, "%Y%m%d").date()
        end = dt.datetime.strptime(args.end, "%Y%m%d").date()
        now = kst_now()
        if start > end or end > now.date():
            raise ValueError("시작일·종료일 순서와 미래 날짜 여부를 확인하세요")
        if end == now.date() and now.hour < 16:
            raise ValueError("오늘 종가는 16시 이후 수집하세요")
        run(Kis(), ym, collect.load_config(), start, end, args.reset)
        return 0
    except (ValueError, FileNotFoundError) as exc:
        print(str(exc))
        return 2
    except KisError as exc:
        print(str(exc))
        return 3 if exc.retryable else 4


if __name__ == "__main__":
    sys.exit(main())
