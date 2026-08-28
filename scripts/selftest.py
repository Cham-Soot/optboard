#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
연결 자가진단 — 앱키를 남에게 보내지 않고도 무엇이 되고 무엇이 안 되는지 확인한다.

  python3 scripts/selftest.py

출력에는 **앱키가 절대 찍히지 않습니다** (앞 4자리만 별표와 함께 표시).
결과를 그대로 복사해 붙여넣어도 안전합니다.
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OK, NO, WARN = "[ 통과 ]", "[ 실패 ]", "[ 주의 ]"
results = []


def mask(s):
    if not s:
        return "(없음)"
    return s[:4] + "*" * max(0, len(s) - 4) + "  (%d자)" % len(s)


def step(title, fn):
    print("\n" + "─" * 62)
    print("▸ " + title)
    try:
        msg = fn()
        print(OK + " " + (msg or ""))
        results.append((title, True))
        return True
    except Exception as e:
        print(NO + " " + str(e).replace(os.environ.get("KIS_APPSECRET", "\x00"), "***"))
        if os.environ.get("SELFTEST_DEBUG"):
            traceback.print_exc()
        results.append((title, False))
        return False


def main():
    print("=" * 62)
    print(" 옵션 누적표 — 연결 자가진단")
    print("=" * 62)

    from kis import Kis, kst_now          # noqa: E402
    import expiry_notice                  # noqa: E402

    api = {}

    def s1():
        import glob
        import kis as kismod
        used = kismod._load_dotenv()
        root = kismod.ROOT
        print("    프로젝트 폴더 : " + root)
        print("    읽은 파일     : " + (used or "(없음)"))

        k, s = os.environ.get("KIS_APPKEY", ""), os.environ.get("KIS_APPSECRET", "")
        print("    앱키    : " + mask(k))
        print("    시크릿  : " + mask(s))
        print("    환경    : " + (os.environ.get("KIS_ENV") or "real"))

        if not k or not s:
            # 폴더에 무엇이 있는지 보여 준다 — 원인이 대개 여기서 드러난다
            found = sorted(os.path.basename(p) for p in glob.glob(os.path.join(root, ".env*")))
            print("    폴더 안의 .env 관련 파일: " + (", ".join(found) or "없음"))
            hint = "  →  python scripts%ssetup_env.py  를 실행하면 .env 를 대신 만들어 줍니다." % os.sep
            if found == [".env.example"]:
                raise RuntimeError(
                    ".env.example 만 있습니다. 이건 견본이라 읽지 않습니다.\n"
                    "           앱키를 .env.example 에 적으셨다면 파일 이름을 .env 로 바꾸거나,\n"
                    "         " + hint)
            if any(f.endswith(".txt") for f in found):
                raise RuntimeError(
                    "메모장이 이름 뒤에 .txt 를 붙인 것 같습니다.\n"
                    "           탐색기에서 '파일 확장명' 표시를 켜고 .env 로 고치거나,\n"
                    "         " + hint)
            raise RuntimeError(".env 가 없습니다.\n         " + hint)

        if len(k) < 20 or len(s) < 40:
            raise RuntimeError("길이가 짧습니다 — 값이 잘려 붙여넣어졌는지 확인해 주세요")
        return "앱키를 읽었습니다"

    def s2():
        api["k"] = Kis()
        t = api["k"].token()
        return "접근토큰 발급 성공 (%d자, 23시간 캐시)" % len(t)

    def s3():
        closed, last = api["k"].closed_days(kst_now().strftime("%Y%m%d"), pages=2)
        soon = [d for d in closed if d >= kst_now().date().isoformat()][:5]
        print("    조회 범위 끝 : " + str(last))
        print("    다가오는 휴장: " + (", ".join(soon) or "없음"))
        return "거래소 달력 %d일 확인" % len(closed)

    def s4():
        ex = api["k"].option_expiries()
        api["ex"] = ex
        print("    거래 중인 월물: " + ", ".join(ex[:6]))
        if not ex:
            raise RuntimeError("월물 목록이 비어 있습니다")
        return "월물 %d개" % len(ex)

    def s5():
        ym = api["ex"][0]
        board, bmeta = api["k"].callput_board(ym)
        api["board"] = board
        api["meta"] = bmeta
        if not board:
            raise RuntimeError("시세판이 비었습니다 (휴장일이면 정상일 수 있음)")
        ks = sorted(board)
        print("    월물 %s · 행사가 %d개 (%s ~ %s)" % (ym, len(ks), ks[0], ks[-1]))
        from kis import implied_index
        print("    역산 지수 %s · 전광판 ATM %s" % (implied_index(board), bmeta.get("atm")))
        c0 = implied_index(board) or bmeta.get("atm")
        if c0 and (ks[0] > c0 or ks[-1] < c0):
            print("    " + WARN + " 등가가 받은 행사가 범위 밖입니다 — 전광판이 잘렸습니다."
                  "  scripts/master.py 를 돌려 두세요")
        elif max(bmeta.get("n_call", 0), bmeta.get("n_put", 0)) >= 100:
            print("    " + WARN + " 100건 상한에 걸렸습니다 — 양 끝이 잘렸을 수 있습니다")
        mid = min(ks, key=lambda s: abs(s - c0)) if c0 else ks[len(ks) // 2]
        c = board[mid].get("c", {})
        p = board[mid].get("p", {})
        print("    표본 %s  콜 시/고/저/종 = %s / %s / %s / %s"
              % (mid, c.get("open"), c.get("high"), c.get("low"), c.get("close")))
        print("            풋 시/고/저/종 = %s / %s / %s / %s"
              % (p.get("open"), p.get("high"), p.get("low"), p.get("close")))
        missing = [n for n, v in (("시가", c.get("open")), ("고가", c.get("high")),
                                  ("저가", c.get("low")), ("종가", c.get("close")))
                   if v is None]
        if missing:
            print("    " + WARN + " 비어 있는 항목: " + ", ".join(missing)
                  + "  (장중이거나 거래가 없는 행사가일 수 있습니다)")
        if not c.get("code"):
            print("    " + WARN + " 종목코드가 비어 있습니다 — 되메우기가 안 될 수 있습니다")
        return "시세판 정상"

    def s6():
        ks = sorted(api["board"])
        code = None
        for k in ks[len(ks) // 2:]:
            code = (api["board"][k].get("c") or {}).get("code")
            if code:
                break
        if not code:
            raise RuntimeError("종목코드를 찾지 못했습니다")
        end = kst_now().date()
        start = end.replace(day=1)
        rows = api["k"].daily_ohlc(code, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
        if not rows:
            raise RuntimeError("일별 시세가 비었습니다 (신규 상장 종목이면 정상)")
        print("    %s : %d일치, 최근 %s 종가 %s"
              % (code, len(rows), rows[-1]["date"], rows[-1]["close"]))
        return "되메우기 경로 정상"

    def s7():
        exp = expiry_notice.next_expiry()
        second = expiry_notice.second_thursday(exp.year, exp.month)
        print("    다음 만기 : %s%s" % (exp, "" if exp == second else "  (둘째 목요일 %s 이 휴장이라 앞당김)" % second))
        return "만기일 계산 정상"

    step("1. 앱키를 읽을 수 있는가", s1) and \
        step("2. 접근토큰이 발급되는가", s2) and \
        step("3. 거래소 휴장일을 받는가 (CTCA0903R)", s3) and \
        step("4. 옵션 월물 목록을 받는가 (FHPIO056104C0)", s4) and \
        step("5. 행사가별 콜·풋 시세판을 받는가 (FHPIF05030100)", s5) and \
        step("6. 종목별 일별 시세를 받는가 (FHKIF03020100)", s6) and \
        step("7. 만기일이 제대로 계산되는가", s7)

    print("\n" + "=" * 62)
    good = sum(1 for _, r in results if r)
    print(" 결과: %d / %d 통과" % (good, len(results)))
    for t, r in results:
        print("   %s %s" % ("○" if r else "✕", t))
    if good == len(results) == 7:
        print("\n 전부 통과했습니다. 이제 collect.py 를 돌리면 됩니다.")
    else:
        print("\n 위 출력을 그대로 붙여넣어 주세요 — 앱키는 찍히지 않습니다.")
    print("=" * 62)
    return 0 if good == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
