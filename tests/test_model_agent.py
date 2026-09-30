"""Synthetic provider transport tests. These are NOT evidence of a real model run."""
import json
from pathlib import Path
import httpx
import pytest
from airlock.common import AirlockError
from airlock.model_agent import ModelAgent,ChatProvider

class ScriptedProvider:
    model='synthetic-test-fixture'
    def __init__(self,responses):self.responses=iter(responses);self.seen=[]
    def complete(self,messages):self.seen.append(list(messages));return next(self.responses)

class ScriptedGateway:
    def __init__(self):self.calls=[];self.pending=False;self.failure=False
    def submit(self,request,key):
        self.calls.append((request.model_dump(),key))
        if self.failure:self.failure=False;raise httpx.ReadTimeout('synthetic interrupted response')
        return {'id':'aaaa-bbbb'}
    def wait(self,ident,timeout):return {'id':ident,'state':'PENDING_APPROVAL' if self.pending else 'SUCCEEDED'}


def call(arguments,name='propose_change'):
    return {'choices':[{'message':{'role':'assistant','content':None,'tool_calls':[{'id':'call_1','type':'function',
        'function':{'name':name,'arguments':json.dumps(arguments)}}]}}],'usage':{'prompt_tokens':10,'completion_tokens':5}}

def final():return {'choices':[{'message':{'role':'assistant','content':'已收到工具结果。'}}]}


def test_provider_uses_tools_and_does_not_echo_error_secrets():
    def handler(request):
        assert request.url==httpx.URL('https://api.deepseek.com/chat/completions')
        assert json.loads(request.content)['tools'][0]['function']['name']=='propose_change'
        return httpx.Response(401,json={'error':'secret-not-to-print'})
    provider=ChatProvider('explicit-model','private-test-key',transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError) as error:provider.complete([{'role':'user','content':'test'}])
    assert 'secret-not-to-print' not in str(error.value) and 'private-test-key' not in str(error.value)
    provider.close()


def test_loop_calls_gateway_and_finishes_with_receipt_only(tmp_path):
    provider=ScriptedProvider([call({'tool':'db.query_rows','limit':2}),final()]);gateway=ScriptedGateway()
    result=ModelAgent(gateway,provider,tmp_path/'private.json').run('读取两条客户')
    assert result['status']=='MODEL_FINISHED' and len(gateway.calls)==1
    assert provider.seen[1][-1]['role']=='tool'
    assert 'SUCCEEDED' in provider.seen[1][-1]['content']
    assert (tmp_path/'private.json').stat().st_mode & 0o777 == 0o600


def test_pending_checkpoint_resume_does_not_resubmit(tmp_path):
    gateway=ScriptedGateway();gateway.pending=True
    provider=ScriptedProvider([call({'tool':'db.query_rows'}),final()]);path=tmp_path/'pending.json'
    result=ModelAgent(gateway,provider,path,wait_seconds=0).run('读取')
    assert result['status']=='WAITING' and len(gateway.calls)==1
    gateway.pending=False
    result=ModelAgent(gateway,provider,path).run(resume=True)
    assert result['status']=='MODEL_FINISHED' and len(gateway.calls)==1


def test_network_loss_resume_reuses_idempotency_key(tmp_path):
    gateway=ScriptedGateway();gateway.failure=True
    provider=ScriptedProvider([call({'tool':'db.query_rows'}),final()]);path=tmp_path/'network.json'
    with pytest.raises(httpx.ReadTimeout):ModelAgent(gateway,provider,path).run('读取')
    result=ModelAgent(gateway,provider,path).run(resume=True)
    assert result['status']=='MODEL_FINISHED'
    assert gateway.calls[0][1]==gateway.calls[1][1]


def test_fabricated_approval_and_unknown_tools_are_not_executed(tmp_path):
    gateway=ScriptedGateway()
    provider=ScriptedProvider([call({'tool':'db.delete_rows','approved':True}),call({},'approve'),final()])
    result=ModelAgent(gateway,provider,tmp_path/'refused.json').run('synthetic adversarial case')
    assert result['status']=='MODEL_FINISHED' and not gateway.calls
    assert any('UNKNOWN_TOOL' in m.get('content','') for m in provider.seen[-1] if isinstance(m.get('content'),str))


def test_no_credentials_is_explicit_not_testable(monkeypatch,capsys):
    import sys
    from airlock.model_agent import main
    monkeypatch.delenv('DEEPSEEK_API_KEY',raising=False)
    monkeypatch.setattr(sys,'argv',['model_agent','读取'])
    assert main()==3
    assert json.loads(capsys.readouterr().out)['status']=='NOT_TESTABLE'
