"""Preserve the existing expiry Issue reminder, with body passed as a UTF-8 file."""
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    notice = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'expiry_notice.py'), '--github'],
                            capture_output=True, text=True, encoding='utf-8')
    if notice.returncode == 1:
        print('만기 알림 대상 없음')
        return 0
    if notice.returncode:
        return notice.returncode
    title, rest = notice.stdout.split('\n', 1)
    body = rest.split('---BODY---', 1)[1].strip()
    tag = re.search(r'\(([^)]+)\)', title).group(1)
    existing = subprocess.check_output(['gh', 'issue', 'list', '--state', 'all', '--search', tag + ' in:title', '--json', 'title'],
                                       text=True, encoding='utf-8')
    if any(tag in item['title'] for item in json.loads(existing)):
        print('이미 등록한 만기 알림')
        return 0
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'notice.md'
        path.write_text(body, encoding='utf-8')
        return subprocess.run(['gh', 'issue', 'create', '--title', title, '--body-file', str(path)]).returncode


if __name__ == '__main__':
    sys.exit(main())
