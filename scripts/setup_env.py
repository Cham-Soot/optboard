#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
.env 파일을 대신 만들어 준다. 메모장을 열 필요가 없다.

  python3 scripts/setup_env.py       (Windows: python scripts\\setup_env.py)

윈도우 메모장은 저장할 때 이름 뒤에 `.txt` 를 몰래 붙이는 일이 잦고,
확장자가 숨겨져 있으면 그게 눈에 보이지도 않는다. 그래서 파일을 직접 쓴다.
앱시크릿은 입력하는 동안 화면에 찍히지 않는다.
"""
import getpass
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = os.path.join(ROOT, ".env")


def confirm(label, default=True):
    """엔터만 쳐도, 입력이 끊겨도 안전한 쪽으로 답한다."""
    try:
        a = input(label).strip().lower()
    except EOFError:
        return default
    if not a:
        return default
    return a in ("y", "yes", "예", "ㅇ")


def ask(label, secret=False, minlen=20):
    while True:
        v = (getpass.getpass(label) if secret else input(label)).strip()
        # 따옴표째 붙여넣는 경우가 잦다
        v = v.strip('"').strip("'").strip()
        if len(v) >= minlen:
            return v
        if not v:
            print("   → 값이 비었습니다. 다시 입력해 주세요.")
        else:
            print("   → %d자밖에 안 됩니다. 잘려서 붙여넣어진 것 같습니다. 다시 해주세요." % len(v))


def main():
    print("=" * 58)
    print(" .env 만들기 — 한국투자증권 앱키를 저장합니다")
    print("=" * 58)
    print(" 저장 위치: %s" % ENV)
    print(" 이 파일은 .gitignore 에 들어 있어 GitHub 에 올라가지 않습니다.\n")

    if os.path.exists(ENV):
        if not confirm(" 이미 .env 가 있습니다. 덮어쓸까요? (y/n) ", default=False):
            print(" 그대로 두었습니다.")
            return 0

    print(" KIS Developers 에서 받은 값을 붙여넣으세요.")
    print(" (마우스 오른쪽 클릭 또는 Ctrl+V 로 붙여넣기가 됩니다)\n")

    key = ask(" 앱키(APP KEY)      : ", minlen=20)
    sec = ask(" 앱시크릿(APP SECRET, 화면에 안 보입니다) : ", secret=True, minlen=40)

    try:
        env = input("\n 실전이면 그냥 엔터, 모의투자면 demo 입력 : ").strip().lower() or "real"
    except EOFError:
        env = "real"
    if env not in ("real", "demo"):
        env = "real"

    with open(ENV, "w", encoding="utf-8", newline="\n") as f:
        f.write("KIS_APPKEY=%s\nKIS_APPSECRET=%s\nKIS_ENV=%s\n" % (key, sec, env))
    try:
        os.chmod(ENV, 0o600)
    except Exception:
        pass

    # .env.example 은 GitHub 에 올라가는 파일이다. 여기에 실제 키가 적혀 있으면 큰일이다.
    example = os.path.join(ROOT, ".env.example")
    if os.path.exists(example):
        try:
            body = open(example, encoding="utf-8-sig", errors="replace").read()
        except Exception:
            body = ""
        if key[:8] in body or sec[:8] in body:
            print("\n" + "!" * 58)
            print(" 경고: .env.example 에 실제 앱키가 적혀 있습니다.")
            print(" 이 파일은 GitHub 에 그대로 올라갑니다 — 반드시 지워야 합니다.")
            print("!" * 58)
            if confirm(" 견본 내용으로 되돌릴까요? (y/n) ", default=True):
                open(example, "w", encoding="utf-8", newline="\n").write(
                    "# 한국투자증권 오픈API 앱키 (실제 값은 .env 에 넣습니다 — 이 파일은 견본입니다)\n"
                    "KIS_APPKEY=발급받은_앱키\n"
                    "KIS_APPSECRET=발급받은_앱시크릿\n"
                    "KIS_ENV=real\n")
                print(" .env.example 을 견본으로 되돌렸습니다.")
            else:
                print(" 직접 지워 주세요. 그대로 두면 GitHub 에 앱키가 공개됩니다.")

    print("\n 저장했습니다.")
    print("   앱키    : %s%s  (%d자)" % (key[:4], "*" * (len(key) - 4), len(key)))
    print("   시크릿  : %s%s  (%d자)" % (sec[:4], "*" * (len(sec) - 4), len(sec)))
    print("   환경    : %s" % env)
    print("\n 이어서 이걸 실행하세요:")
    print("   python scripts%sselftest.py" % os.sep)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n 취소했습니다.")
        sys.exit(1)
