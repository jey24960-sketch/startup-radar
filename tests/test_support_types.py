import os
import psycopg
import pytest
from radar.support_types import SupportType, contract, normalize
from radar.extraction import Extraction
from radar.models import Program
from test_database import db
from test_web_runtime import context
from test_member_results import rpc, detail


def test_extraction_enum_and_exact_raw_mapping():
    assert Extraction.model_json_schema()['$defs']['SupportType']['enum']==[t.value for t in SupportType]
    assert set(contract()['raw_mapping']['시설ㆍ공간ㆍ보육'])=={'WORKSPACE','INCUBATION'}
    assert normalize(['경영','수출','WORKSPACE','WORKSPACE'])==['UNKNOWN','GLOBAL','WORKSPACE']
    assert normalize(['SPACE','New unknown source category'])==['UNKNOWN']
    assert Program(title='x',organization='x',official_url='https://example.org',program_types=['수출']).program_types==['GLOBAL']
    default=Program(title='x',organization='x',official_url='https://example.org')
    assert Program.model_validate(default.model_dump(mode='json'))==default


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit ephemeral database required')
def test_database_contract_filters_and_history_preservation(context):
    c=context
    with c['db'].transaction(c['admin']) as con:
        assert con.execute('select startup_radar.support_type_contract() value').fetchone()['value']==contract()
        for raw in ([],['경영','수출','WORKSPACE'],['시설ㆍ공간ㆍ보육','WORKSPACE'],['SPACE']):
            assert con.execute('select startup_radar.normalize_support_types(%s) value',(raw,)).fetchone()['value']==normalize(raw)
    assert rpc(c,'gfc_radar_me')['support_types']==contract()['types']
    for t in SupportType:
        with c['db'].transaction() as con:
            con.execute('update startup_radar.programs set program_types=%s where id=%s',([t.value],c['saved']['program_id']))
        result=rpc(c,'gfc_radar_programs',(None,0,'',t.value))
        assert result['total']==1 and result['items'][0]['id']==str(c['saved']['program_id'])
    with pytest.raises(psycopg.errors.InvalidParameterValue):rpc(c,'gfc_radar_programs',(None,0,'','SPACE'))
    # Projection normalizes legacy raw values without altering immutable evidence.
    with c['db'].transaction() as con:
        before=con.execute('select normalized from startup_radar.program_versions where id=%s',(c['saved']['version_id'],)).fetchone()['normalized']
    assert detail(c)['facts']['program_types']==normalize(before['program_types'])
    with c['db'].transaction() as con:
        assert con.execute('select normalized from startup_radar.program_versions where id=%s',(c['saved']['version_id'],)).fetchone()['normalized']==before
