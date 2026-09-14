from copy import deepcopy
import pytest
from radar.scheduler import ingestion_execution_result


def partial(failure,discovered=5,parsed=5):
    return {'status':'PARTIAL_SUCCESS','id':'retained-run','sources':[{
        'status':'PARTIAL','discovered':discovered,'fetched':discovered,'parsed':parsed,'failures':[failure]}]}


@pytest.mark.parametrize('failure',[{'stage':'DOCUMENT','kind':'DOCUMENT_OCR_REQUIRED'},
    {'stage':'EXTRACTION','kind':'AI_DATE_EVIDENCE'}])
def test_completed_import_retains_partial_source_health_and_warning(failure):
    raw=partial(failure);original=deepcopy(raw)
    result=ingestion_execution_result(raw)
    assert result['status']=='SUCCESS' and result['ingestion_status']=='PARTIAL_SUCCESS'
    assert result['completed_with_warnings'] and result['sources']==original['sources']
    assert raw==original


@pytest.mark.parametrize('raw',[
    partial({'kind':'PAGE_LIMIT'}),
    partial({'kind':'HTTP'}),partial({'kind':'NORMALIZE_OR_PERSIST'},parsed=4),
    partial({'stage':'EXTRACTION','kind':'SOURCE_REVIEW_CHANGED'}),
    partial({'stage':'EXTRACTION','kind':'AuthenticationError'}),
    partial({'stage':'EXTRACTION','kind':'PermissionDeniedError'}),
    partial({'stage':'EXTRACTION','kind':'AI_NOT_CONFIGURED'}),
    {**partial({'kind':'PAGE_LIMIT'}),'alerts':{'status':'PARTIAL_SUCCESS','failed':1}},
    partial({'kind':'PAGE_LIMIT'},discovered=0,parsed=0),
    {'status':'FAILED','sources':[]},{'status':'PARTIAL_SUCCESS','sources':[]}])
def test_actual_or_empty_failures_never_become_success(raw):
    assert ingestion_execution_result(raw)==raw
