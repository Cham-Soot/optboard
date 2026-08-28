#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
지수옵션 종목코드 마스터를 받아 data/optcodes.json 에 저장한다.

왜 필요한가
-----------
전광판 API(FHPIF05030100)는 콜·풋 **각 100건**이 상한인데, 행사가가 높은 쪽부터
100개를 내주는 바람에 정작 등가(ATM) 근처가 통째로 잘려 나간다.
(2026-08 기준: 지수 약 1,089 인데 전광판은 1350 부터만 내려왔다)

그래서 거래소 종목코드 마스터를 직접 받는다. 여기에는 **모든 행사가의 종목코드**가
들어 있어서, 원하는 행사가의 코드를 뽑아 종목별 조회로 시세를 가져올 수 있다.

  python3 scripts/master.py            # 받아서 저장 (하루 한 번이면 충분)
  python3 scripts/master.py --dump     # 파싱이 제대로 됐는지 원본 샘플까지 출력

인증이 필요 없는 공개 파일이라 앱키 없이도 받아진다.
"""
import argparse
import datetime as dt
import io
import json
import os
import re
import ssl
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "optcodes.json")
URL = "https://new.real.download.dws.co.kr/common/master/fo_idx_code_mts.mst.zip"

# 상품종류 — 우리가 쓰는 건 KOSPI200 지수옵션뿐이다
CALL, PUT = "5", "6"
KIND = {"5": "지수콜옵션", "6": "지수풋옵션", "1": "지수선물",
        "D": "미니콜옵션", "E": "미니풋옵션",
        "J": "코스닥150콜", "K": "코스닥150풋",
        "L": "위클리콜옵션", "M": "위클리풋옵션"}

KST = dt.timezone(dt.timedelta(hours=9))


def download():
    ssl._create_default_https_context = ssl._create_unverified_context
    raw = urllib.request.urlopen(URL, timeout=90).read()
    z = zipfile.ZipFile(io.BytesIO(raw))
    name = z.namelist()[0]
    return z.read(name).decode("cp949", errors="replace"), name


def parse(text):
    """
    파이프(|)로 나뉜 마스터를 읽는다. 컬럼 순서는 한국투자증권 공식 정제 스크립트 기준:
      상품종류 | 단축코드 | 표준코드 | 한글종목명 | ATM구분 | 행사가 | 월물구분코드 |
      기초자산 단축코드 | 기초자산명
    """
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        f = line.split("|")
        if len(f) < 7:
            continue
        try:
            strike = float(f[5].strip())
        except ValueError:
            strike = None
        rows.append({
            "kind": f[0].strip(),
            "code": f[1].strip(),
            "std": f[2].strip(),
            "name": f[3].strip(),
            "atm": f[4].strip(),
            "strike": strike,
            "mmsc": f[6].strip(),          # 1:최근월물 2:차근 3:차차근 4:차차차근
        })
    return rows


def month_after(yyyymm, n):
    y, m = int(yyyymm[:4]), int(yyyymm[4:6])
    t = (y * 12 + m - 1) + n
    return "%04d%02d" % (t // 12, t % 12 + 1)


def near_month(today=None):
    """오늘 기준 최근월물(YYYYMM). 이번 달 만기가 지났으면 다음 달."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from expiry_notice import expiry_of
    d = today or dt.datetime.now(KST).date()
    return ("%04d%02d" % (d.year, d.month)) if expiry_of(d.year, d.month) >= d \
        else month_after("%04d%02d" % (d.year, d.month), 1)


def build(rows, dump=False):
    opts = [r for r in rows if r["kind"] in (CALL, PUT) and r["strike"] is not None]
    near = near_month()

    if dump:
        from collections import Counter
        print("\n상품종류 분포:")
        for k, n in sorted(Counter(r["kind"] for r in rows).items()):
            print("   %-3s %-12s %6d" % (k, KIND.get(k, "?"), n))
        print("\n지수옵션 원본 샘플 (콜 3줄 / 풋 3줄):")
        for t in (CALL, PUT):
            for r in [x for x in opts if x["kind"] == t][:3]:
                print("   %s | %s | %s | ATM=%s | 행사가=%s | 월물구분=%s"
                      % (r["kind"], r["code"], r["name"], r["atm"], r["strike"], r["mmsc"]))
        print("\n월물구분코드 분포: ", end="")
        print(dict(Counter(r["mmsc"] for r in opts)))

    # 실측(2026-08): 월물구분코드는 비어 있고, 한글종목명에 YYYYMM 이 그대로 들어 있다.
    #   예)  5 | B01609335 | "C 202609   335.0" | ATM=2 | 행사가=335.0
    # 그래서 종목명에서 년월을 읽는 쪽이 본선이고, 월물구분코드는 예비 경로로 남겨 둔다.
    table, unmapped = {}, 0
    for r in opts:
        m = re.search(r"(20\d{2})(0[1-9]|1[0-2])", r["name"])
        if m:
            ym = m.group(1) + m.group(2)
        elif r["mmsc"] in ("1", "2", "3", "4"):
            ym = month_after(near, int(r["mmsc"]) - 1)
        else:
            unmapped += 1
            continue
        slot = table.setdefault(ym, {}).setdefault("%g" % r["strike"], {})
        slot["c" if r["kind"] == CALL else "p"] = r["code"]

    doc = {
        "source": "KRX 지수선물옵션 종목마스터 (fo_idx_code_mts.mst)",
        "near_month": near,
        "updated": dt.datetime.now(KST).isoformat(timespec="seconds"),
        "months": table,
    }
    return doc, unmapped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true", help="원본 샘플과 통계까지 출력")
    args = ap.parse_args()

    print("종목코드 마스터를 받는 중… (약 몇 MB)")
    try:
        text, fname = download()
    except Exception as e:
        print("실패: %s" % e)
        print("회사 네트워크가 막고 있을 수 있습니다. 개인 네트워크에서 다시 시도해 보세요.")
        return 1
    print("  받음: %s  (%d줄)" % (fname, len(text.splitlines())))

    rows = parse(text)
    doc, unmapped = build(rows, dump=args.dump)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)

    print("\n최근월물: %s" % doc["near_month"])
    print("월물별 행사가 개수:")
    for ym in sorted(doc["months"])[:8]:
        ks = sorted(float(k) for k in doc["months"][ym])
        both = sum(1 for v in doc["months"][ym].values() if "c" in v and "p" in v)
        print("   %s : 행사가 %3d개  (%g ~ %g)  콜·풋 모두 있는 것 %d개"
              % (ym, len(ks), ks[0], ks[-1], both))
    if len(doc["months"]) > 8:
        print("   … 외 %d개 월물" % (len(doc["months"]) - 8))
    if unmapped:
        print("\n월물을 알아내지 못한 줄 %d개 (원월물일 가능성이 큽니다 — 근월물 수집에는 지장 없음)"
              % unmapped)
    print("\n저장: %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
