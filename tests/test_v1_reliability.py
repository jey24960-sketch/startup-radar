import json
from types import SimpleNamespace
from unittest.mock import Mock
from datetime import timedelta

import pytest
import main
from core import analyzer, notifier
from core.clock import today
from core.results import AnalysisResult, Failure, DeliveryResult


def program(i=1):
    return dict(title=f'Program {i}', organization='GFC', source='K-Startup', summary='Useful',
                relevance_score=80, deadline=(today()+timedelta(days=30)).isoformat())


def client(text, **extra):
    return SimpleNamespace(messages=SimpleNamespace(create=Mock(return_value=SimpleNamespace(
        content=[SimpleNamespace(type='text', text=text)], **extra))))


def test_empty_is_success():
    result = analyzer._call_claude(client('[]'), {'source':'text'})
    assert result.status == 'SUCCESS' and result.programs == []


@pytest.mark.parametrize('text,kind', [('garbage','JSON'), ('["x"]','SCHEMA'), ('{}','SCHEMA')])
def test_analysis_errors_are_typed(text, kind):
    result = analyzer._call_claude(client(text), {'source':'text'})
    assert result.status == 'FAILED'
    assert result.failures[0].kind == kind


def test_string_brackets_parse():
    p = program(); p['summary']='literal [ brackets ]'
    assert analyzer._call_claude(client(json.dumps([p])), {'source':'text'}).programs == [p]


def test_timeout_not_empty_success():
    c=client('[]'); c.messages.create.side_effect=TimeoutError()
    assert analyzer._call_claude(c, {'source':'text'}).status == 'FAILED'


def test_partial_analysis_keeps_good_programs(monkeypatch):
    monkeypatch.setattr(analyzer, '_build_chunks', lambda data:[{'a':'x'},{'b':'y'}])
    monkeypatch.setattr(analyzer, '_call_claude', Mock(side_effect=[AnalysisResult([program()], successful_chunks=1),
        AnalysisResult(failures=[Failure('API','unavailable')])]))
    result=analyzer.analyze({'a':'x','b':'y'}, 'test-key')
    assert result.status == 'PARTIAL_SUCCESS' and len(result.programs)==1


def test_closed_programs_removed():
    p=program(); p['deadline']=(today()-timedelta(days=1)).isoformat()
    assert analyzer._call_claude(client(json.dumps([p])), {'source':'text'}).programs == []


def test_only_displayed_programs_are_delivered(monkeypatch):
    monkeypatch.setattr(notifier, '_send_one', lambda *args:True)
    items=[program(i) for i in range(9)]; recorded=[]
    result=notifier.send_telegram_notification(items, [], 13, 'unused', 'unused', on_delivered=recorded.extend)
    assert result.delivered == recorded == items[:7]
    assert result.pending == items[7:]


def test_partial_delivery_records_only_success(monkeypatch):
    monkeypatch.setattr(notifier, '_send_one', Mock(side_effect=[True,True,False,True]))
    items=[program(i) for i in range(3)]; recorded=[]
    result=notifier.send_telegram_notification(items, [], 13, 'unused','unused',on_delivered=recorded.extend)
    assert recorded == [items[0],items[2]] and result.failed == [items[1]]
    assert not result.ok


def test_failed_fragment_not_recorded(monkeypatch):
    monkeypatch.setattr(notifier, '_split_message',lambda text:['one','two'])
    monkeypatch.setattr(notifier, '_send_one',Mock(side_effect=[True,True,False]))
    recorded=[]
    result=notifier.send_telegram_notification([program()],[],1,'x','x',on_delivered=recorded.extend)
    assert not recorded and result.failed


def test_failure_message_not_no_programs(monkeypatch):
    sent=[]
    monkeypatch.setattr(notifier,'_send_one',lambda text,*args: sent.append(text) or True)
    notifier.send_telegram_notification([],['broken'],1,'x','x',analysis_failures=[Failure('API','error')])
    assert '새로운 공고가 없습니다' not in sent[0] and '오류' in sent[0]


def prepare_run(monkeypatch,tmp_path):
    monkeypatch.setattr(main,'load_secrets',lambda:dict(ANTHROPIC_API_KEY='x',TELEGRAM_BOT_TOKEN='x',TELEGRAM_CHAT_ID='x'))
    monkeypatch.setattr(main,'DATA_DIR',str(tmp_path))
    monkeypatch.setattr(main,'cleanup_expired',lambda **kw:None)
    monkeypatch.setattr(main,'filter_new_programs',lambda p:p)
    monkeypatch.setattr(main,'mark_as_sent',lambda p:None)


def test_critical_failure_exits_nonzero(monkeypatch,tmp_path):
    prepare_run(monkeypatch,tmp_path)
    monkeypatch.setattr(main,'crawl_all',lambda:({},['failed']))
    monkeypatch.setattr(main,'analyze',lambda *a,**kw:AnalysisResult(failures=[Failure('API','failed')]))
    monkeypatch.setattr(main,'send_telegram_notification',lambda *a,**kw:DeliveryResult())
    assert main.run_full()==1


def test_valid_results_delivered_despite_partial_failure(monkeypatch,tmp_path):
    prepare_run(monkeypatch,tmp_path)
    monkeypatch.setattr(main,'crawl_all',lambda:({'ok':'text'},['failed']))
    monkeypatch.setattr(main,'analyze',lambda *a,**kw:AnalysisResult([program()],successful_chunks=1))
    send=Mock(return_value=DeliveryResult([program()]))
    monkeypatch.setattr(main,'send_telegram_notification',send)
    assert main.run_full()==1
    assert send.call_args.args[0]==[program()]


def test_dry_run_needs_no_telegram_and_preserves_delivery_state(monkeypatch,tmp_path):
    import config
    monkeypatch.setenv('ANTHROPIC_API_KEY','test-only')
    monkeypatch.delenv('TELEGRAM_BOT_TOKEN',raising=False)
    monkeypatch.delenv('TELEGRAM_CHAT_ID',raising=False)
    monkeypatch.setattr(main,'DATA_DIR',str(tmp_path))
    monkeypatch.setattr(main,'crawl_all',lambda:({'ok':'text'},[]))
    monkeypatch.setattr(main,'analyze',lambda *a,**kw:AnalysisResult([program()],successful_chunks=1))
    monkeypatch.setattr(main,'filter_new_programs',lambda p:p)
    forbidden=Mock(side_effect=AssertionError('Dry run must not mutate delivery state'))
    for name in ('cleanup_expired','mark_as_sent','send_telegram_notification'):
        monkeypatch.setattr(main,name,forbidden)
    assert main.run_full(dry_run=True)==0
    forbidden.assert_not_called()
    report=json.loads(next(tmp_path.glob('report_*_run.json')).read_text(encoding='utf-8'))
    assert report['collection_started_at']<=report['collection_completed_at']<=report['analysis_completed_at']
    assert report['observed_at']==report['collection_started_at'] and report['delivery_enabled'] is False
    assert report['collected_sources']==['ok'] and report['minimum_relevance_score']==60
    with pytest.raises(ValueError,match='TELEGRAM_BOT_TOKEN'):
        config.load_secrets()
