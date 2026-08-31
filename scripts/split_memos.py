#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
시세 파일 안에 섞여 있는 메모를 빼내어 개인 파일(data/marks.json)로 옮긴다.

왜 필요한가
-----------
`data/{월물}.json` 은 GitHub에 올라간다. 여기에 메모가 들어 있으면 **매매 판단이 공개된다.**
시세는 공개 정보라 괜찮지만 메모는 다르다. 그래서 둘을 갈라 놓는다.

  data/{월물}.json   시세만          → 저장소에 올라감 (공개)
  data/marks.json    마킹 + 메모      → .gitignore 가 막음 (내 PC에만)

  python3 scripts/split_memos.py            # 옮기기
  python3 scripts/split_memos.py --dry-run  # 무엇이 옮겨질지만 보기
"""
import argparse
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
MARKS = os.path.join(DATA, "marks.json")


def fmt_strike(s):
    s = float(s)
    return ("%g" % s) if s % 1 else str(int(s))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        marks = json.load(open(MARKS, encoding="utf-8"))
    except Exception:
        marks = {}
    memos = marks.get("memos") or {}
    marks.setdefault("marks", {})

    moved = 0
    targets = sorted(glob.glob(os.path.join(DATA, "[0-9][0-9][0-9][0-9].json")) +
                     glob.glob(os.path.join(ROOT, "archive", "[0-9][0-9][0-9][0-9].json")))
    for path in targets:
        doc = json.load(open(path, encoding="utf-8"))
        hit = 0
        for r in doc.get("rows", []):
            m1, m2 = (r.get("memo1") or "").strip(), (r.get("memo2") or "").strip()
            if not m1 and not m2:
                continue
            k = "%s|%s|%s" % (doc["expiry"], fmt_strike(r["strike"]), r["date"])
            old = memos.get(k) or ["", ""]
            memos[k] = [m1 or old[0], m2 or old[1]]     # 이미 있던 메모를 덮지 않는다
            r["memo1"], r["memo2"] = "", ""
            hit += 1
        # 봉인본은 별도 memos 칸도 갖고 있다
        if doc.get("memos"):
            for k, v in doc["memos"].items():
                if v and (v[0] or v[1]):
                    memos.setdefault(k, v)
                    hit += 1
            doc["memos"] = {}
        if doc.get("marks"):
            marks["marks"].update(doc["marks"])
            doc["marks"] = {}
        if hit:
            moved += hit
            print("  %-28s 메모 %3d건 분리" % (os.path.relpath(path, ROOT), hit))
            if not args.dry_run:
                json.dump(doc, open(path, "w", encoding="utf-8"),
                          ensure_ascii=False, separators=(",", ":"))

    marks["memos"] = memos
    if args.dry_run:
        print("\n(연습 실행) 옮길 메모 %d건. 실제로는 아무것도 바꾸지 않았습니다." % moved)
        return 0

    json.dump(marks, open(MARKS, "w", encoding="utf-8"), ensure_ascii=False)
    print("\n메모 %d건을 data/marks.json 으로 옮겼습니다." % moved)
    print("이 파일은 .gitignore 가 막고 있어 GitHub 에 올라가지 않습니다.")
    print("시세 파일에는 이제 숫자만 남았습니다.")
    if moved:
        print("\n다음: python3 scripts/build_viewer.py 로 화면을 다시 만드세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
