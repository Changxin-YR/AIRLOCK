import json
import httpx
import pytest
from airlock.semantic import ProviderConfig,SemanticAdvisor
from test_semantic import payload


def configuration(tmp_path):
    path=tmp_path/'deepseek.json'
    path.write_text(json.dumps({'authorized_project':'AIRLOCK','provider':'deepseek_responses','model':'deepseek-flash',
        'currency':'CNY','budget_cny':5.0,'max_calls':3,'input_cny_per_million':2.0,'cached_input_cny_per_million':0.04,
        'output_cny_per_million':8.0,'price_source':'offline price fixture','price_effective_date':'2026-10-02'}))
    return path


def test_deepseek_fixed_endpoint_currency_cache_and_invalidation(tmp_path,monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY','synthetic-deepseek-credential')
    monkeypatch.setenv('AIRLOCK_LLM_API_KEY','must-not-be-forwarded')
    def respond(request):
        assert request.url==httpx.URL('https://api.deepseek.com/responses')
        assert request.headers['Authorization']=='Bearer synthetic-deepseek-credential'
        body=json.loads(request.content)
        assert body['reasoning']=={'effort':'none'} and body['model']=='deepseek-flash' and 'tools' not in body
        return httpx.Response(200,json=payload({'risk':'low','score':0.1,'reason':'offline fixture'}))
    advisor=SemanticAdvisor(configuration(tmp_path),tmp_path/'budget',httpx.MockTransport(respond))
    result=advisor.assess({'request':'SELECT 1'})
    assert result['status']=='ok' and result['currency']=='CNY' and result['cost_usd'] is None
    assert result['cost_cny']==pytest.approx((40*2+10*.04+20*8)/1_000_000)
    cached=advisor.assess({'request':'SELECT 1'})
    assert cached['application_cache_hit'] and cached['cost_cny'] is None and cached['cost_amount'] is None
    assert advisor.invalidate_cache()=={'invalidated':1,'total_invalidations':1}
    assert not advisor.assess({'request':'SELECT 1'})['application_cache_hit']
    assert advisor.ledger_summary()['calls']==2


def test_currency_mismatch_cannot_reuse_budget(tmp_path):
    path=configuration(tmp_path);base=tmp_path/'ledger'
    SemanticAdvisor(path,base)
    data=json.loads(path.read_text());data.update(currency='USD',budget_usd=1.0,input_usd_per_million=1.0,
        cached_input_usd_per_million=0.1,output_usd_per_million=2.0)
    for key in list(data):
        if '_cny' in key:del data[key]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='across providers or currencies'):SemanticAdvisor(path,base)


def test_price_configuration_requires_one_currency(tmp_path):
    data=json.loads(configuration(tmp_path).read_text());data['budget_usd']=1.0
    with pytest.raises(ValueError):ProviderConfig.model_validate(data)
