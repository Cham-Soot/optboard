"""Explicit boundary between public market data and private annotations."""
import copy
import json
import math
from pathlib import Path


def public_doc(doc):
    allowed = ("expiry", "label", "product", "strikes", "dates", "updated", "sealed", "collection")
    out = {k: copy.deepcopy(doc[k]) for k in allowed if k in doc}
    out["rows"] = [{k: copy.deepcopy(row[k]) for k in ("date", "strike", "c", "p")}
                   for row in doc.get("rows", [])]
    return out


def assert_public(doc, context="data"):
    for key in ("marks", "memos", "MYDATA"):
        if doc.get(key):
            raise ValueError("%s: 개인 데이터가 공개 파일에 포함되어 있습니다 (%s)" % (context, key))
    seen = set()
    for row in doc.get("rows", []):
        if row.get("memo1") or row.get("memo2") or row.get("marks") or row.get("memos"):
            raise ValueError("%s: 메모가 포함된 행을 공개할 수 없습니다" % context)
        identity = (row["date"], float(row["strike"]))
        if identity in seen:
            raise ValueError("%s: 중복된 날짜/행사가" % context)
        seen.add(identity)
        for side in ("c", "p"):
            values = row[side]
            if not isinstance(values, list) or len(values) != 4:
                raise ValueError("%s: 잘못된 시세 배열" % context)
            if any(v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))
                                      or not math.isfinite(v) or v < 0) for v in values):
                raise ValueError("%s: 잘못된 가격" % context)


def atomic_json(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    temp.replace(path)


def script_json(value):
    # JSON is embedded in an HTML script element, not only parsed as JSON.
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
