"""Run the scheduled stages and expose a precise, bounded retry result to Actions."""
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys

from public_data import atomic_json
from kis import kst_now

ROOT = Path(__file__).resolve().parent.parent


def scheduled_day(now, cal):
    """A delayed morning run collects the most recent completed regular session."""
    from collect import open_day
    day = now.date()
    if now.hour < 16:
        day -= dt.timedelta(days=1)
        while not open_day(day.isoformat(), cal):
            day -= dt.timedelta(days=1)
    return day.isoformat()


def describe_report(report, code):
    names = {"complete": "당일 수집 완료", "complete_with_warnings": "당일 수집 완료 · 과거 자료 확인 필요",
             "incomplete": "당일 일부 미완료", "failed": "수집 실패", "closed": "휴장일"}
    title = "%s · %s" % (report.get("date", ""), names.get(report.get("status"), "수집 상태 확인 필요"))
    daily = report.get("daily", {})
    if daily.get("expected_count"):
        title += " (%d/%d 종목 확인)" % (daily.get("complete_count", 0), daily["expected_count"])
    details = list(report.get("errors", [])) + list(report.get("warnings", []))
    lines = [title, "종료코드: %s (0 완료/주의, 2 설정·거래일 오류, 3 연결 오류, 4 당일 미완료)" % code]
    lines.extend(details)
    for item in report.get("history", {}).get("days", []):
        lines.append("과거 %s %s: %s/%s 종목 확인" %
                     (item["expiry"], item["date"], item["complete_count"], item["expected_count"]))
    return title, lines


def annotation(value):
    return str(value).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main():
    expiry, day = os.getenv("INPUT_EXPIRY", "").strip(), os.getenv("INPUT_DATE", "").strip()
    retry = os.getenv("INPUT_RETRY", "0").strip() or "0"
    code, stage = 2, "input"
    input_day, input_error = day, None
    try:
        from collect import check_expiry
        if expiry:
            check_expiry(expiry)
        if day:
            dt.date.fromisoformat(day)
        if not retry.isdigit() or not 0 <= int(retry) <= 4:
            raise ValueError("재시도 횟수는 0~4입니다")
        for stage in ("master", "calendar_sync", "collect"):
            command = [sys.executable, str(ROOT / "scripts" / (stage + ".py"))]
            if stage == "collect":
                if not day and os.getenv("GITHUB_EVENT_NAME") == "schedule":
                    from collect import calendar_data, open_day
                    cal = calendar_data()
                    candidate = scheduled_day(kst_now(), cal)
                    if open_day(candidate, cal):
                        day = candidate
                        print("예약 실행 대상 거래일: " + day, flush=True)
                if expiry: command += ["--expiry", expiry]
                if day: command += ["--date", day]
                if not input_day and not expiry: command += ["--heal"]
            code = subprocess.run(command, cwd=ROOT).returncode
            if code:
                break
    except ValueError as exc:
        code, input_error = 2, str(exc)
        print(input_error)
    if stage != "collect" or input_error:
        atomic_json(ROOT / "data" / "collection_status.json", {
            "checked":kst_now().isoformat(timespec="seconds"), "date":day or kst_now().date().isoformat(),
            "status":"failed", "errors":[input_error or "수집 준비 단계 실패: " + stage], "stage":stage})
    report = json.loads((ROOT / "data" / "collection_status.json").read_text(encoding="utf-8"))
    title, lines = describe_report(report, code)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        import html
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
            summary.write("## 시세 수집 결과\n\n" + "\n\n".join(html.escape(line) for line in lines) + "\n")
    for message in report.get("errors", []):
        print("::error::" + annotation(message))
    for message in report.get("warnings", []):
        print("::warning::" + annotation(message))
    if os.getenv("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write("code=%d\nretry=%d\n" % (code, int(retry) if retry.isdigit() and int(retry) <= 4 else 4))
            detail = title + (" · " + "; ".join(report.get("errors", [])) if code else "")
            output.write("date=%s\ndetail=%s\n" % (day or report.get("date", ""),
                         detail.replace("\r", " ").replace("\n", " ")[:2000]))
    print("자동 수집 결과: 단계=%s, 종료코드=%s" % (stage, code))
    # Actions checkpoints partial data and deploys the status before reporting failure.
    return 0


if __name__ == "__main__":
    sys.exit(main())
