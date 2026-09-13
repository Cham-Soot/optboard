"""Run the scheduled stages and expose a precise, bounded retry result to Actions."""
import datetime as dt
import os
from pathlib import Path
import subprocess
import sys

from public_data import atomic_json
from kis import kst_now

ROOT = Path(__file__).resolve().parent.parent


def main():
    expiry, day = os.getenv("INPUT_EXPIRY", "").strip(), os.getenv("INPUT_DATE", "").strip()
    retry = os.getenv("INPUT_RETRY", "0").strip() or "0"
    code, stage = 2, "input"
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
                if expiry: command += ["--expiry", expiry]
                if day: command += ["--date", day]
            code = subprocess.run(command, cwd=ROOT).returncode
            if code:
                break
    except ValueError as exc:
        print(str(exc))
    if stage != "collect":
        atomic_json(ROOT / "data" / "collection_status.json", {
            "checked":kst_now().isoformat(timespec="seconds"), "date":day or kst_now().date().isoformat(),
            "status":"failed", "errors":["수집 준비 단계 실패: " + stage], "stage":stage})
    if os.getenv("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write("code=%d\nretry=%d\n" % (code, int(retry) if retry.isdigit() and int(retry) <= 4 else 4))
    print("자동 수집 결과: 단계=%s, 종료코드=%s" % (stage, code))
    # Actions checkpoints partial data and deploys the status before reporting failure.
    return 0


if __name__ == "__main__":
    sys.exit(main())
