import contextlib
import copy
import datetime as dt
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import collect
import calendar_sync
from kis import KisError, Kis
from public_data import public_doc, assert_public, script_json

DAY = '2026-09-11'
CFG = {'PRODUCT':'TEST', 'RANGE_MODE':'atm', 'ATM_SPAN':1, 'STRIKE_MIN':None, 'STRIKE_MAX':None, 'MONTHS':'near2'}
NOW = dt.datetime(2026,9,11,17,tzinfo=dt.timezone(dt.timedelta(hours=9)))
def price(day=DAY):
    return {'date':day,'open':10,'high':12,'low':8,'close':11,'volume':4}
def document():
    return {'expiry':'2610','label':'TEST','product':'TEST','strikes':[],'dates':[],'rows':[]}


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.enterContext(patch.object(collect, 'DATA', self.tmp.name))
        self.enterContext(patch.object(collect, 'kst_now', return_value=NOW))
        self.enterContext(patch.object(collect.time, 'sleep'))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.enterContext(patch.object(collect, 'load_codes', return_value={1100.0:{'c':'C','p':'P'}}))
        self.api = Mock()
        self.api.index_ohlc.return_value = {DAY:1100, '2026-09-10':1100}
        self.api.daily_ohlc.return_value = [price()]

    def read(self):
        return collect.load_doc('202610','TEST')

    def test_current_board_never_used_for_historical_date(self):
        collect.collect_one(self.api,'202610',CFG,DAY,use_board=True)
        self.api.callput_board.assert_not_called()
        self.assertEqual(self.read()['rows'][0]['date'], DAY)

    def test_wrong_date_rejected_and_day_incomplete(self):
        self.api.daily_ohlc.return_value = [price('2026-09-10')]
        with self.assertRaises(collect.CollectionIncomplete):
            collect.collect_one(self.api,'202610',CFG,DAY)
        self.assertEqual(self.read()['rows'], [])
        self.assertEqual(self.read()['collection'][DAY]['status'], 'incomplete')

    def test_partial_failure_preserves_existing_prices_and_repair_is_targeted(self):
        doc=document();collect.upsert(doc,DAY,1100,[1,2,1,2],[20,22,18,21]);collect.save_doc(doc)
        self.api.daily_ohlc.side_effect = lambda code,*args: [price()] if code=='C' else (_ for _ in ()).throw(KisError('network',retryable=True))
        with self.assertRaises(collect.CollectionIncomplete) as caught:
            collect.collect_one(self.api,'202610',CFG,DAY)
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(self.read()['rows'][0]['p'], [20,22,18,21])
        self.api.daily_ohlc.reset_mock(side_effect=True)
        self.api.daily_ohlc.return_value=[price()]
        collect.collect_range(self.api,'202610',CFG,[DAY],repair_only=True)
        self.assertEqual(self.api.daily_ohlc.call_count,1)
        self.assertEqual(self.api.daily_ohlc.call_args.args[0],'P')
        self.assertEqual(self.read()['collection'][DAY]['status'],'complete')

    def test_period_query_batches_days_by_contract(self):
        self.api.daily_ohlc.return_value=[price('2026-09-10'),price()]
        collect.collect_range(self.api,'202610',CFG,['2026-09-10',DAY])
        self.assertEqual(self.api.daily_ohlc.call_count,2)
        self.assertEqual(len(self.read()['rows']),2)

    def test_zero_volume_is_distinct_from_missing_response(self):
        self.api.daily_ohlc.return_value=[{**price(),'volume':0}]
        collect.collect_one(self.api,'202610',CFG,DAY)
        self.assertEqual(self.read()['collection'][DAY]['contracts']['1100|c']['status'],'no_trade')
        self.assertEqual(self.read()['rows'][0]['c'],[None]*4)

    def test_invalid_ohlc_not_saved(self):
        self.api.daily_ohlc.return_value=[{**price(),'high':3}]
        with self.assertRaises(collect.CollectionIncomplete):collect.collect_one(self.api,'202610',CFG,DAY)
        self.assertEqual(self.read()['rows'],[])

    def test_zero_volume_does_not_certify_contradictory_existing_price(self):
        doc=document();collect.upsert(doc,DAY,1100,[1,2,1,2],[20,22,18,21]);collect.save_doc(doc)
        self.api.daily_ohlc.return_value=[{**price(),'volume':0}]
        with self.assertRaises(collect.CollectionIncomplete):
            collect.collect_one(self.api,'202610',CFG,DAY)
        self.assertEqual(self.read()['rows'][0]['c'],[1,2,1,2])
        self.assertEqual(self.read()['collection'][DAY]['status'],'incomplete')

    def test_historical_index_selects_historical_range(self):
        with patch.object(collect,'load_codes',return_value={100:{'c':'C','p':'P'},150:{'c':'X','p':'Y'},200:{'c':'Z','p':'W'}}):
            self.api.index_ohlc.return_value={DAY:100}
            collect.collect_one(self.api,'202610',CFG,DAY)
        codes={c.args[0] for c in self.api.daily_ohlc.call_args_list}
        self.assertEqual(codes,{'C','P','X','Y'})

    def test_all_failures_return_nonzero(self):
        cal={'from':'2026-01-01','to':'2027-01-01','closed':[],'updated':DAY}
        self.api.daily_ohlc.side_effect=KisError('network',retryable=True)
        with patch.object(collect,'calendar_data',return_value=cal),patch.object(collect,'load_config',return_value=CFG),patch.object(collect,'Kis',return_value=self.api),patch.object(sys,'argv',['collect','--expiry','202610','--date',DAY]):
            self.assertEqual(collect.main(),3)

    def test_invalid_expiry_checked_before_authentication(self):
        with patch.object(collect,'Kis') as provider,patch.object(sys,'argv',['collect','--expiry',DAY]):
            self.assertEqual(collect.main(),2)
        provider.assert_not_called()

    def run_main(self, dated=False):
        cal={'from':'2026-01-01','to':'2027-01-01','closed':[],'updated':DAY}
        self.api.option_expiries.return_value=['202610']
        argv=['collect'] + (['--date',DAY] if dated else [])
        with patch.object(collect,'calendar_data',return_value=cal),patch.object(collect,'load_config',return_value=CFG),patch.object(collect,'Kis',return_value=self.api),patch.object(sys,'argv',argv):
            code=collect.main()
        return code,json.loads((Path(self.tmp.name)/'collection_status.json').read_text(encoding='utf-8'))

    def test_transient_invalid_price_rechecks_only_failed_contract(self):
        self.api.daily_ohlc.side_effect=[[{**price(),'high':3}],[price()],[price()]]
        code,report=self.run_main(dated=True)
        self.assertEqual(code,0)
        self.assertEqual(report['status'],'complete')
        self.assertEqual([call.args[0] for call in self.api.daily_ohlc.call_args_list],['C','P','C'])
        self.assertEqual(self.read()['rows'][0]['c'],[10,12,8,11])

    def test_persistent_invalid_price_still_fails(self):
        self.api.daily_ohlc.return_value=[{**price(),'high':3}]
        code,report=self.run_main(dated=True)
        self.assertEqual(code,4)
        self.assertEqual(report['status'],'incomplete')
        self.assertEqual(self.read()['rows'],[])
        self.assertIn('고가=3',report['errors'][0])

    def test_historical_conflict_remains_visible_without_failing_complete_today(self):
        doc=document()
        collect.upsert(doc,'2026-09-10',1100,[1,2,1,2],[20,22,18,21])
        collect.save_doc(doc)
        self.api.daily_ohlc.side_effect=lambda code,start,end: [price()] if start=='20260911' else [{**price('2026-09-10'),'volume':0}]
        with patch.object(collect,'recent_open_days',return_value=['2026-09-10']):
            code,report=self.run_main()
        self.assertEqual(code,0)
        self.assertEqual(report['status'],'complete_with_warnings')
        self.assertEqual(report['daily'],{'expected_count':2,'complete_count':2})
        self.assertEqual(report['history']['incomplete_count'],2)
        self.assertTrue(report['warnings'])
        saved=self.read()
        self.assertEqual(saved['rows'][0]['c'],[1,2,1,2])
        self.assertEqual(saved['collection']['2026-09-10']['contracts']['1100|c']['status'],'invalid')
        self.api.daily_ohlc.side_effect=None
        self.api.daily_ohlc.return_value=[price()]
        _,later=self.run_main(dated=True)
        self.assertEqual(later['status'],'complete_with_warnings')
        self.assertEqual(later['history']['incomplete_count'],2)

    def test_missing_contract_date_is_repaired_even_when_date_exists(self):
        self.api.daily_ohlc.side_effect=lambda code,*args: [price()] if code=='C' else []
        with self.assertRaises(collect.CollectionIncomplete):collect.collect_one(self.api,'202610',CFG,DAY)
        with patch.object(collect,'recent_open_days',return_value=[DAY]),patch.object(collect,'collect_range') as repair:
            collect.heal_missing(self.api,['202610'],CFG,'2026-09-14')
        self.assertEqual(repair.call_args.args[3],[DAY])


class BoundaryTests(unittest.TestCase):
    def test_public_projection_removes_personal_fields(self):
        doc=document();collect.upsert(doc,DAY,1100,[1,2,1,2],[1,2,1,2]);doc['rows'][0]['memo1']='PRIVATE';doc['memos']={'x':'PRIVATE'}
        with self.assertRaises(ValueError):assert_public(doc)
        public=public_doc(doc)
        assert_public(public)
        self.assertNotIn('PRIVATE',json.dumps(public))
        self.assertEqual(doc['rows'][0]['memo1'],'PRIVATE')

    def test_script_closing_tag_is_escaped(self):
        encoded=script_json({'memo':'</script><script>alert(1)</script>'})
        self.assertNotIn('<',encoded)
        self.assertEqual(json.loads(encoded)['memo'],'</script><script>alert(1)</script>')

    def test_calendar_refreshes_stale_long_horizon(self):
        fake=Mock();fake.closed_days.return_value=(['2026-09-12'],'2027-01-01')
        with tempfile.TemporaryDirectory() as temp,patch.object(calendar_sync,'PATH',str(Path(temp)/'calendar.json')),patch.object(calendar_sync,'load',return_value={'from':'2026-01-01','to':'2028-01-01','updated':'2026-01-01','closed':[]}),patch.object(calendar_sync,'Kis',return_value=fake),patch.object(calendar_sync,'kst_now',return_value=NOW),patch.object(sys,'argv',['calendar']),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(calendar_sync.main(),0)
        fake.closed_days.assert_called_once()

    def test_daily_api_filters_out_of_range_response(self):
        api=Kis(appkey='TEST',appsecret='TEST')
        with patch.object(api,'_daily_page',return_value=[price('2026-09-10'),price()]):
            self.assertEqual(api.daily_ohlc('TEST','20260911','20260911'),[price()])


if __name__=='__main__':unittest.main()
