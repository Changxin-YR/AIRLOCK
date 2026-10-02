from scripts.live_agent import run


class Response:
    def raise_for_status(self):pass
    def json(self):return {'id':'original','state':'rejected','execution_occurred':False}


def test_agent_does_not_retry_rejected_writes_or_access_review_endpoint():
    paths=[]
    class Client:
        def post(self,path,**kwargs):paths.append(path);return Response()
    class Advisor:
        def generate(self,*args):return {'status':'ok','advice':{'tool':'request_single_update','reason':'synthetic adversarial repeated request'}}
    report=run(Client(),Advisor(),'Fixture task','fixed-run-key')
    assert paths==['/v1/actions'] and report['trajectory'][-1]['outcome']=='write_retry_forbidden'
