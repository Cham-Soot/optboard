import contextlib
import datetime as dt
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import run_collection as runner

CAL={'from':'2026-01-01','to':'2027-01-01','closed':['2026-09-14']}
ZONE=dt.timezone(dt.timedelta(hours=9))


class RunnerTests(unittest.TestCase):
    def test_delayed_run_uses_last_closed_session_and_respects_holidays(self):
        self.assertEqual(runner.scheduled_day(dt.datetime(2026,9,15,0,58,tzinfo=ZONE),CAL),'2026-09-11')
        self.assertEqual(runner.scheduled_day(dt.datetime(2026,9,15,21,tzinfo=ZONE),CAL),'2026-09-15')
        self.assertEqual(runner.scheduled_day(dt.datetime(2026,9,12,1,tzinfo=ZONE),CAL),'2026-09-11')

    def test_retry_output_keeps_resolved_day_and_explains_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'data').mkdir()
            report={'date':'2026-09-14','status':'incomplete','errors':['가격 관계 불일치'],
                    'daily':{'expected_count':2,'complete_count':1}}
            (root/'data/collection_status.json').write_text(json.dumps(report),encoding='utf-8')
            env={'INPUT_DATE':'','INPUT_EXPIRY':'','INPUT_RETRY':'0','GITHUB_EVENT_NAME':'schedule',
                 'GITHUB_OUTPUT':str(root/'output'),'GITHUB_STEP_SUMMARY':str(root/'summary')}
            with patch.object(runner,'ROOT',root),patch.dict(os.environ,env),patch.object(runner,'kst_now',return_value=dt.datetime(2026,9,15,0,58,tzinfo=ZONE)),patch('collect.calendar_data',return_value={**CAL,'closed':[]}),patch.object(runner.subprocess,'run',side_effect=[Mock(returncode=0),Mock(returncode=0),Mock(returncode=4)]) as calls,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(runner.main(),0) # checkpoints still run after a partial failure
            self.assertEqual(calls.call_args.args[0][-3:],['--date','2026-09-14','--heal'])
            outputs=(root/'output').read_text(encoding='utf-8')
            self.assertIn('code=4',outputs)
            self.assertIn('date=2026-09-14',outputs)
            self.assertIn('가격 관계 불일치',outputs)
            self.assertIn('1/2 종목',(root/'summary').read_text(encoding='utf-8'))

    def test_explicit_date_is_not_changed_by_delayed_schedule(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'data').mkdir()
            (root/'data/collection_status.json').write_text('{"status":"closed","date":"2026-09-10"}',encoding='utf-8')
            with patch.object(runner,'ROOT',root),patch.dict(os.environ,{'INPUT_DATE':'2026-09-10','INPUT_EXPIRY':'','INPUT_RETRY':'0','GITHUB_EVENT_NAME':'schedule','GITHUB_OUTPUT':'','GITHUB_STEP_SUMMARY':''}),patch.object(runner.subprocess,'run',return_value=Mock(returncode=0)) as calls,contextlib.redirect_stdout(io.StringIO()):
                runner.main()
            self.assertEqual(calls.call_args.args[0][-2:],['--date','2026-09-10'])

    def test_warning_summary_keeps_historical_counts(self):
        title,lines=runner.describe_report({'date':'2026-09-15','status':'complete_with_warnings',
             'daily':{'complete_count':320,'expected_count':320},'warnings':['과거 가격은 보존했습니다'],
             'history':{'days':[{'expiry':'202610','date':'2026-09-11','complete_count':111,'expected_count':160}]}},0)
        self.assertIn('당일 수집 완료',title)
        self.assertIn('과거 자료 확인 필요',title)
        self.assertIn('320/320',title)
        self.assertTrue(any('111/160' in line for line in lines))


if __name__=='__main__': unittest.main()
