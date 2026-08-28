#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
viewer_template.html + data/*.json  ->  index.html

data/ 안의 월물 파일은 절대 지우지 않습니다. 만기가 지난 월물도 그대로 보관되고,
화면 드롭다운에는 항상 전체 목록이 뜹니다.

  python3 scripts/build_viewer.py             # 전체 월물을 index.html 안에 심음 (기본)
  python3 scripts/build_viewer.py --recent 6  # 최근 6개만 심고 나머지는 열 때 불러옴
"""
import argparse
import datetime
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(ROOT, 'viewer_template.html')
OUT = os.path.join(ROOT, 'index.html')
DATA = os.path.join(ROOT, 'data')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--recent', type=int, default=0,
                    help='index.html 에 심을 최근 월물 개수 (0 = 전부)')
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(DATA, '[0-9][0-9][0-9][0-9].json')))
    docs = [json.load(open(f, encoding='utf-8')) for f in files]
    docs.sort(key=lambda d: d['expiry'])

    # 목록은 언제나 전체 — 여기가 과거 월물이 사라지던 자리였습니다
    catalog = [{'expiry': d['expiry'],
                'label': d.get('label', ''),
                'days': len(d.get('dates', [])),
                'first': (d.get('dates') or [''])[0],
                'last': (d.get('dates') or [''])[-1]} for d in docs]

    embed = docs if args.recent <= 0 else docs[-args.recent:]
    payload = json.dumps(embed, ensure_ascii=False, separators=(',', ':'))
    cat_payload = json.dumps(catalog, ensure_ascii=False, separators=(',', ':'))

    # 만기일표를 심어 둔다 — 화면이 직접 휴장일을 따질 필요가 없도록
    import datetime as _dt
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from expiry_notice import expiry_of
    today = _dt.date.today()
    exp_map = {}
    for i in range(-36, 18):
        yy, mm = divmod((today.year * 12 + today.month - 1) + i, 12)
        exp_map['%s%02d' % (str(yy)[2:], mm + 1)] = expiry_of(yy, mm + 1).isoformat()

    html = open(TPL, encoding='utf-8').read()
    html = (html.replace('/*__DATA__*/[]', payload)
                .replace('/*__CATALOG__*/[]', cat_payload)
                .replace('/*__EXPIRIES__*/{}', json.dumps(exp_map, separators=(',', ':'))))
    open(OUT, 'w', encoding='utf-8').write(html)

    json.dump({'expiries': [d['expiry'] for d in docs],
               'catalog': catalog,
               'built': datetime.datetime.utcnow().isoformat(timespec='seconds') + 'Z'},
              open(os.path.join(DATA, 'index.json'), 'w', encoding='utf-8'),
              ensure_ascii=False)

    print('index.html %.0f KB — 보관 월물 %d개, 내장 %d개'
          % (len(html) / 1024, len(docs), len(embed)))


if __name__ == '__main__':
    main()
