#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build public pages from an allowlist. Private HTML requires --private."""
import argparse
import datetime as dt
import json
from pathlib import Path
import shutil
from expiry_notice import expiry_of
from public_data import public_doc, assert_public, atomic_json, script_json

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ("marking-core.mjs", "memo-core.mjs", "memo-sync.mjs", "firebase-config.mjs")


def build(recent=3, site_dir=None, private=False):
    docs = []
    for path in sorted((ROOT / "data").glob("[0-9][0-9][0-9][0-9].json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert_public(raw, path.name)
        docs.append(public_doc(raw))
    docs.sort(key=lambda d: d["expiry"])
    catalog = [{"expiry": d["expiry"], "label": d.get("label", ""), "days": len(d.get("dates", [])),
                "first": (d.get("dates") or [""])[0], "last": (d.get("dates") or [""])[-1]} for d in docs]
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    expiries = {}
    for i in range(-36, 18):
        yy, mm = divmod(now.year * 12 + now.month - 1 + i, 12)
        expiries["%s%02d" % (str(yy)[2:], mm + 1)] = expiry_of(yy, mm + 1).isoformat()
    template = (ROOT / "viewer_template.html").read_text(encoding="utf-8")
    def render(embed, my=None):
        out = template
        for marker, value in (("/*__DATA__*/[]", embed), ("/*__CATALOG__*/[]", catalog),
                              ("/*__EXPIRIES__*/{}", expiries), ("/*__MYMARKS__*/null", my)):
            if out.count(marker) != 1:
                raise ValueError("템플릿 자리표시자가 없거나 중복됩니다: " + marker)
            out = out.replace(marker, script_json(value))
        return out
    html = render(docs[-recent:] if recent > 0 else docs)
    (ROOT / "index.html").write_text(html, encoding="utf-8")
    manifest = {"expiries": [d["expiry"] for d in docs], "catalog": catalog,
                "built": now.astimezone(dt.timezone.utc).isoformat(timespec="seconds")}
    atomic_json(ROOT / "data" / "index.json", manifest)
    if private:
        marks = json.loads((ROOT / "data" / "marks.json").read_text(encoding="utf-8"))
        target = ROOT / ".private" / "내화면.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        offline = render(docs, marks).replace('<script type="module" src="assets/memo-sync.mjs"></script>', '')
        engine = (ROOT / "assets" / "marking-core.mjs").read_text(encoding="utf-8").replace("export ", "")
        memo = (ROOT / "assets" / "memo-core.mjs").read_text(encoding="utf-8")
        memo = memo.replace("import {CELLS, COLORS, isPlanKey} from './marking-core.mjs';", "").replace("export {isPlanKey};", "").replace("export ", "")
        engine = '<script>(()=>{' + engine + memo + '\nwindow.optboardMarkingEngine={deriveMarks,priceAt,planKey,decodeBackup};})();</script>\n'
        offline = offline.replace('<script>', engine + '<script>', 1)
        target.write_text(offline, encoding="utf-8")
        print("개인용 화면: " + str(target))
    if site_dir:
        site = (ROOT / site_dir).resolve()
        if site == ROOT or ROOT not in site.parents:
            raise ValueError("공개 출력은 저장소 안의 별도 폴더여야 합니다")
        site.mkdir(parents=True, exist_ok=True)
        (site / "index.html").write_text(html, encoding="utf-8")
        atomic_json(site / "data" / "index.json", manifest)
        for doc in docs:
            atomic_json(site / "data" / (doc["expiry"] + ".json"), doc)
        for name in ASSETS:
            target = site / "assets" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "assets" / name, target)
        health = ROOT / "data" / "collection_status.json"
        if health.exists():
            atomic_json(site / "data" / health.name, json.loads(health.read_text(encoding="utf-8")))
        for name in ("robots.txt", ".nojekyll"):
            if (ROOT / name).exists():
                shutil.copyfile(ROOT / name, site / name)
        permitted = {"index.html", "robots.txt", ".nojekyll", "data/index.json", "data/collection_status.json"}
        permitted.update("data/" + d["expiry"] + ".json" for d in docs)
        permitted.update("assets/" + name for name in ASSETS)
        extra = [str(path.relative_to(site)) for path in site.rglob("*")
                 if path.is_file() and path.relative_to(site).as_posix() not in permitted]
        if extra:
            raise ValueError("공개 출력에 허용하지 않은 파일이 있습니다: " + ", ".join(extra))
    print("공개 화면 생성 — 월물 %d개, 개인 메모 포함 없음" % len(docs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recent", type=int, default=3)
    ap.add_argument("--site-dir", help="Pages 배포용 공개 파일만 생성 (예: _site)")
    ap.add_argument("--private", action="store_true", help="명시적으로 개인용 오프라인 화면 생성")
    args = ap.parse_args()
    build(args.recent, args.site_dir, args.private)


if __name__ == "__main__":
    main()
