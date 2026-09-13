import contextlib
import datetime as dt
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import archive
import backfill
import build_viewer
import collect
from public_data import atomic_json

ROOT = Path(__file__).resolve().parents[1]


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'data').mkdir()
        self.enterContext(patch.object(collect, 'ROOT', str(self.root)))
        self.enterContext(patch.object(collect, 'DATA', str(self.root / 'data')))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def test_failed_reset_leaves_original_byte_identical(self):
        original = self.root / 'data' / '2610.json'
        original.write_text('{"unchanged":true}', encoding='utf-8')
        atomic_json(self.root / 'data' / 'optcodes.json', {'months':{}})
        api = Mock(); api.index_ohlc.return_value = {'2026-09-11':1090}
        with patch.object(collect, 'collect_range', side_effect=collect.CollectionIncomplete('missing')):
            with self.assertRaises(collect.CollectionIncomplete):
                backfill.run(api, '202610', {'PRODUCT':'test'}, dt.date(2026,9,11), dt.date(2026,9,11), True)
        self.assertEqual(original.read_text(encoding='utf-8'), '{"unchanged":true}')
        self.assertEqual(collect.DATA, str(self.root / 'data'))

    def test_public_build_does_not_open_or_embed_private_file(self):
        source = json.loads((ROOT / 'data' / '2507.json').read_text(encoding='utf-8'))
        atomic_json(self.root / 'data' / '2507.json', source)
        (self.root / 'data' / 'marks.json').write_text('INVALID PRIVATE JSON', encoding='utf-8')
        shutil.copyfile(ROOT / 'viewer_template.html', self.root / 'viewer_template.html')
        shutil.copytree(ROOT / 'assets', self.root / 'assets')
        with patch.object(build_viewer, 'ROOT', self.root):
            build_viewer.build(site_dir='_site')
        self.assertNotIn('INVALID PRIVATE JSON', (self.root / '_site' / 'index.html').read_text(encoding='utf-8'))
        self.assertFalse((self.root / '_site' / 'data' / 'marks.json').exists())
        self.assertFalse((self.root / '.private').exists())
        (self.root / '_site' / 'secret.txt').write_text('unlisted')
        with patch.object(build_viewer, 'ROOT', self.root), self.assertRaises(ValueError):
            build_viewer.build(site_dir='_site')

    def test_archive_is_public_even_with_private_marks_on_same_pc(self):
        doc = {'expiry':'2507','label':'test','strikes':[100],'dates':['2025-07-10'],
               'rows':[{'date':'2025-07-10','strike':100,'c':[1,2,1,2],'p':[1,2,1,2]}]}
        atomic_json(self.root / 'data' / '2507.json', doc)
        atomic_json(self.root / 'data' / 'marks.json', {'memos':{'2507|100|2025-07-10':['PRIVATE','']}})
        with patch.object(archive, 'ROOT', str(self.root)), patch.object(archive, 'DATA', str(self.root / 'data')), \
             patch.object(archive, 'ARCH', str(self.root / 'archive')), patch.object(sys, 'argv', ['archive']):
            self.assertEqual(archive.main(), 0)
        self.assertNotIn('PRIVATE', (self.root / 'archive' / '2507.json').read_text(encoding='utf-8'))
        from openpyxl import load_workbook
        book = load_workbook(self.root / 'archive' / '2507.xlsx')
        self.assertIsNone(book.active['J2'].value)
        book.close()


if __name__ == '__main__': unittest.main()
