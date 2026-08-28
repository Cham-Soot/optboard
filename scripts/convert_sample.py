import json, datetime, openpyxl, os, re

SRC = '/root/.claude/uploads/561d9b79-fcb4-551f-81a2-4107d31ca35b/c15485b2-25__7__.xlsx'
OUT = '/home/claude/optboard/data/2507.json'

def serial_to_date(n):
    return (datetime.date(1899,12,30) + datetime.timedelta(days=int(n))).isoformat()

def norm_strike(name):
    v = int(name)
    return v + 0.5 if v % 5 != 0 else float(v)

wb = openpyxl.load_workbook(SRC, data_only=True)
rows = []
strikes = []
for ws in wb.worksheets:
    if not re.fullmatch(r'\d+', ws.title):
        continue
    strike = norm_strike(ws.title)
    strikes.append(strike)
    for r in ws.iter_rows(min_row=2, values_only=True):
        serial = r[4]
        if serial is None or not isinstance(serial,(int,float)):
            continue
        c = r[0:4]; p = r[5:9]
        memos = [str(x).strip() for x in r[9:17] if x not in (None,'') and str(x).strip()]
        if all(v is None for v in c) and all(v is None for v in p) and not memos:
            continue
        rows.append({
            'date': serial_to_date(serial),
            'strike': strike,
            'c': [None if v is None else float(v) for v in c],
            'p': [None if v is None else float(v) for v in p],
            'memo1': memos[0] if len(memos)>0 else '',
            'memo2': memos[1] if len(memos)>1 else '',
        })

strikes = sorted(set(strikes))
dates = sorted({r['date'] for r in rows})
doc = {
    'expiry': '2507',
    'label': '25년 7월물',
    'product': 'KOSPI200 옵션',
    'strikes': strikes,
    'dates': dates,
    'updated': None,
    'rows': rows,
}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT,'w',encoding='utf-8') as f:
    json.dump(doc,f,ensure_ascii=False,separators=(',',':'))
print('strikes',len(strikes),strikes[:5],'...',strikes[-3:])
print('dates',len(dates),dates[0],'~',dates[-1])
print('rows',len(rows))
print('memos',sum(1 for r in rows if r['memo1'] or r['memo2']))
print('size',os.path.getsize(OUT))
