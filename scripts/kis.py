#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
한국투자증권(KIS) 오픈API 최소 클라이언트 — 국내 지수옵션 시세 전용.

필요한 것: 앱키 / 앱시크릿 두 개뿐입니다.
  KIS_APPKEY, KIS_APPSECRET   (환경변수 또는 .env 파일)
  KIS_ENV                     real(실전, 기본) | demo(모의)

접근토큰은 발급 후 24시간 유효하고 재발급 호출에 제한이 있어
token_cache.json 에 저장해 두고 재사용합니다.
"""
import json
import os
import time
import datetime as dt
import urllib.parse
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".token_cache.json")

HOSTS = {
    "real": "https://openapi.koreainvestment.com:9443",
    "demo": "https://openapivts.koreainvestment.com:29443",
}


#  .env 를 찾을 때 살펴본 경로 — 진단에서 쓴다
ENV_TRIED = []
ENV_USED = None


def _load_dotenv():
    """
    `.env` 를 읽는다. 윈도우 메모장이 이름 뒤에 `.txt` 를 몰래 붙이는 일이 잦아
    `.env.txt` 도 함께 받아 준다. (`.env.example` 은 견본이라 읽지 않는다)
    """
    global ENV_USED
    del ENV_TRIED[:]
    for name in (".env", ".env.txt", ".env.env"):
        p = os.path.join(ROOT, name)
        ENV_TRIED.append(p)
        if not os.path.exists(p):
            continue
        # 메모장이 UTF-8 BOM 을 붙이는 경우가 있어 utf-8-sig 로 연다
        for line in open(p, encoding="utf-8-sig", errors="replace"):
            line = line.strip().lstrip("﻿")
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        ENV_USED = p
        return p
    return None


_load_dotenv()


class KisError(RuntimeError):
    pass


class Kis:
    def __init__(self, appkey=None, appsecret=None, env=None):
        self.appkey = appkey or os.environ.get("KIS_APPKEY", "")
        self.appsecret = appsecret or os.environ.get("KIS_APPSECRET", "")
        self.env = (env or os.environ.get("KIS_ENV") or "real").lower()
        if not self.appkey or not self.appsecret:
            raise KisError(
                "KIS_APPKEY / KIS_APPSECRET 이 없습니다. "
                ".env 파일에 넣거나 환경변수로 지정해 주세요."
            )
        self.host = HOSTS[self.env]
        self._token = None

    # ---------- 접근토큰 ----------
    def token(self):
        if self._token:
            return self._token
        cached = self._read_cache()
        if cached:
            self._token = cached
            return cached

        body = json.dumps({
            "grant_type": "client_credentials",
            "appkey": self.appkey,
            "appsecret": self.appsecret,
        }).encode()
        req = urllib.request.Request(
            self.host + "/oauth2/tokenP", data=body,
            headers={"content-type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                res = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raise KisError("접근토큰 발급 실패: %s %s" % (e.code, e.read().decode()[:300]))

        tok = res.get("access_token")
        if not tok:
            raise KisError("접근토큰 응답에 access_token 이 없습니다: %s" % res)
        # 발급 후 24시간 유효 — 여유를 두고 23시간만 사용
        self._write_cache(tok, time.time() + 23 * 3600)
        self._token = tok
        return tok

    def _read_cache(self):
        try:
            d = json.load(open(CACHE, encoding="utf-8"))
            if d.get("env") == self.env and d.get("exp", 0) > time.time() + 60:
                return d["token"]
        except Exception:
            pass
        return None

    def _write_cache(self, token, exp):
        try:
            json.dump({"token": token, "exp": exp, "env": self.env},
                      open(CACHE, "w", encoding="utf-8"))
            os.chmod(CACHE, 0o600)
        except Exception:
            pass

    # ---------- 공통 호출 ----------
    def get(self, path, tr_id, params, retries=3, tr_cont="", with_headers=False):
        # KIS 의 연속조회 키에는 공백이 그대로 들어 있다. 반드시 URL 인코딩해야 한다.
        qs = urllib.parse.urlencode({k: ("" if v is None else str(v))
                                     for k, v in params.items()},
                                    quote_via=urllib.parse.quote)
        url = self.host + path + "?" + qs
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": "Bearer " + self.token(),
            "appkey": self.appkey,
            "appsecret": self.appsecret,
            "tr_id": tr_id,
            "custtype": "P",
        }
        if tr_cont:
            headers["tr_cont"] = tr_cont
        last = None
        for i in range(retries):
            try:
                req = urllib.request.Request(url, headers=headers, method="GET")
                with urllib.request.urlopen(req, timeout=30) as r:
                    res = json.loads(r.read().decode())
                    got = dict(r.headers)
                if str(res.get("rt_cd", "0")) != "0":
                    raise KisError("%s: %s" % (res.get("msg_cd"), res.get("msg1")))
                return (res, got) if with_headers else res
            except (urllib.error.HTTPError, urllib.error.URLError, KisError) as e:
                last = e
                time.sleep(1.5 * (i + 1))
        raise KisError("API 호출 실패 (%s): %s" % (tr_id, last))

    # ---------- 거래소 휴장일 ----------
    def closed_days(self, bass_dt, pages=12):
        """
        한국거래소 개장 달력. bass_dt('YYYYMMDD') 이후로 **문을 닫는 날**을 모아 돌려준다.
        (주말·공휴일·근로자의날·연말 폐장·임시 휴장이 전부 여기에 들어 있다)

        ※ KIS 안내: 원장 서비스와 엮여 있어 **하루 1회 정도만** 호출할 것.
        반환: (닫는 날 리스트, 조회가 닿은 마지막 날짜)
        """
        closed, last_day = [], None
        fk = nk = ""
        cont = ""
        for _ in range(pages):
            res, hdr = self.get("/uapi/domestic-stock/v1/quotations/chk-holiday",
                                "CTCA0903R",
                                {"BASS_DT": bass_dt, "CTX_AREA_FK": fk, "CTX_AREA_NK": nk},
                                tr_cont=cont, with_headers=True)
            rows = res.get("output") or []
            if not isinstance(rows, list):
                rows = [rows]
            for r in rows:
                d = (r.get("bass_dt") or "").strip()
                if len(d) != 8:
                    continue
                iso = "%s-%s-%s" % (d[:4], d[4:6], d[6:])
                last_day = iso
                if (r.get("opnd_yn") or "").strip().upper() != "Y":
                    closed.append(iso)
            cont_flag = (hdr.get("tr_cont") or hdr.get("Tr_Cont") or "").strip()
            if cont_flag not in ("M", "F"):
                break
            fk, nk, cont = res.get("ctx_area_fk", ""), res.get("ctx_area_nk", ""), "N"
            time.sleep(0.4)
        return sorted(set(closed)), last_day

    # ---------- 옵션 조회 ----------
    def option_expiries(self):
        """거래 중인 옵션 월물 목록. 근월물이 맨 앞. -> ['202609', '202610', ...]"""
        res = self.get("/uapi/domestic-futureoption/v1/quotations/display-board-option-list",
                       "FHPIO056104C0",
                       {"FID_COND_SCR_DIV_CODE": "509",
                        "FID_COND_MRKT_DIV_CODE": "",
                        "FID_COND_MRKT_CLS_CODE": ""})
        out = res.get("output") or []
        ex = []
        for row in out:
            v = (row.get("mtrt_yymm") or row.get("mtrt_yymm_code") or "").strip()
            if len(v) >= 6 and v[:6].isdigit():
                ex.append(v[:6])
        return sorted(set(ex))

    def callput_board(self, yyyymm):
        """
        한 월물의 전 행사가 콜/풋 현재 시세판.
        반환: (board, meta)
          board = {행사가(float): {'c': {...}, 'p': {...}}}   각 값은 open/high/low/close/volume/code
          meta  = {'index': 지수 기준가, 'atm': ATM 행사가, 'n_call':, 'n_put':}
        ※ KIS 제약: 콜·풋 각각 100건까지. 조회가 느리므로 1초 1회 이내로 호출.
        """
        res = self.get("/uapi/domestic-futureoption/v1/quotations/display-board-callput",
                       "FHPIF05030100",
                       {"FID_COND_MRKT_DIV_CODE": "O",
                        "FID_COND_SCR_DIV_CODE": "20503",
                        "FID_MRKT_CLS_CODE": "CO",
                        "FID_MTRT_CNT": yyyymm,
                        "FID_MRKT_CLS_CODE1": "PO",
                        "FID_COND_MRKT_CLS_CODE": ""})
        board = {}
        meta = {"index": None, "atm": None, "n_call": 0, "n_put": 0}
        for side, rows in (("c", res.get("output1") or []), ("p", res.get("output2") or [])):
            meta["n_call" if side == "c" else "n_put"] = len(rows)
            for row in rows:
                try:
                    strike = float(row.get("acpr"))
                except (TypeError, ValueError):
                    continue
                board.setdefault(strike, {})[side] = {
                    "open":   _f(row.get("optn_oprc")),
                    "high":   _f(row.get("optn_hgpr")),
                    "low":    _f(row.get("optn_lwpr")),
                    "close":  _f(row.get("optn_prpr")),
                    "volume": _i(row.get("acml_vol")),
                    "code":   (row.get("optn_shrn_iscd") or "").strip(),
                }
                if meta["index"] is None:
                    meta["index"] = _f(row.get("nmix_sdpr"))
                if (row.get("atm_cls_name") or "").strip().upper().startswith("ATM"):
                    meta["atm"] = strike
        # ATM 표시가 없으면 콜·풋 종가가 가장 비슷한 행사가로 어림한다
        if meta["atm"] is None:
            best, gap = None, None
            for s, v in board.items():
                c, p = (v.get("c") or {}).get("close"), (v.get("p") or {}).get("close")
                if c is None or p is None:
                    continue
                g = abs(c - p)
                if gap is None or g < gap:
                    best, gap = s, g
            meta["atm"] = best
        return board, meta

    def daily_ohlc(self, code, d1, d2):
        """
        종목코드 하나의 일별 OHLC. d1/d2 = 'YYYYMMDD'.
        API 가 한 번에 100건까지만 주므로 긴 구간은 130일씩 나눠 받는다.
        """
        start = dt.date(int(d1[:4]), int(d1[4:6]), int(d1[6:]))
        stop = dt.date(int(d2[:4]), int(d2[4:6]), int(d2[6:]))
        seen, cur = {}, start
        while cur <= stop:
            end = min(stop, cur + dt.timedelta(days=130))
            for r in self._daily_page(code, cur.strftime("%Y%m%d"), end.strftime("%Y%m%d")):
                seen[r["date"]] = r
            if end >= stop:
                break
            cur = end + dt.timedelta(days=1)
            time.sleep(0.15)
        return [seen[k] for k in sorted(seen)]

    def _daily_page(self, code, d1, d2):
        res = self.get("/uapi/domestic-futureoption/v1/quotations/inquire-daily-fuopchartprice",
                       "FHKIF03020100",
                       {"FID_COND_MRKT_DIV_CODE": "O",
                        "FID_INPUT_ISCD": code,
                        "FID_INPUT_DATE_1": d1,
                        "FID_INPUT_DATE_2": d2,
                        "FID_PERIOD_DIV_CODE": "D"})
        out = []
        for r in (res.get("output2") or []):
            date = (r.get("stck_bsop_date") or "").strip()
            if len(date) != 8:
                continue
            out.append({
                "date": "%s-%s-%s" % (date[:4], date[4:6], date[6:]),
                "open": _f(r.get("futs_oprc")), "high": _f(r.get("futs_hgpr")),
                "low": _f(r.get("futs_lwpr")), "close": _f(r.get("futs_prpr")),
                "volume": _i(r.get("acml_vol")),
            })
        return out


def implied_index(board):
    """
    풋-콜 패리티로 지수를 역산한다:  지수 ≈ 행사가 + 콜종가 - 풋종가

    전광판이 등가에서 멀리 떨어진 행사가만 내줘도 지수는 정확히 나온다.
    (2026-08-28 예: 1350 + 0.41 - 260.7 = 1089.7 → 실제 KOSPI200 1088.6)
    응답의 nmix_sdpr 은 지수가 아니어서 쓰지 않는다.
    """
    est = []
    for s, v in board.items():
        c = (v.get("c") or {}).get("close")
        p = (v.get("p") or {}).get("close")
        if c is None or p is None:
            continue
        est.append(s + c - p)
    if not est:
        return None
    est.sort()
    n = len(est)
    return round(est[n // 2] if n % 2 else (est[n // 2 - 1] + est[n // 2]) / 2, 2)


def _f(v):
    try:
        f = float(str(v).strip())
        return None if f == 0 else f
    except (TypeError, ValueError):
        return None


def _i(v):
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return 0


def kst_now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
