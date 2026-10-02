from dataclasses import replace
import json
import time
import uuid
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
import pytest
from airlock.api import create_app
from conftest import call, decision, count


def issuer(settings, tmp_path):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    key.update(kid='issuer-1', alg='RS256', use='sig')
    (tmp_path/'jwks.json').write_text(json.dumps({'keys':[key]}))
    config = {'issuer':'https://issuer.example/tenant', 'audience':'https://airlock.example',
              'jwks_file':'jwks.json', 'subjects':{'review-human':'reviewer:oidc','agent-service':'agent:demo'}}
    path = tmp_path/'oidc.json'; path.write_text(json.dumps(config))
    reviewers = tmp_path/'reviewers.json'
    reviewers.write_text(json.dumps({'reviewers':[{'id':'reviewer:oidc','tools':['sql'],
        'resources':['customers'],'risks':['low','high','critical','blocked']}]}))
    def token(subject='review-human', headers=None, **overrides):
        now=int(time.time())
        claims={'iss':config['issuer'],'aud':config['audience'],'sub':subject,'iat':now,'exp':now+300,
                'jti':uuid.uuid4().hex,'client_id':'review-console'} | overrides
        return jwt.encode(claims,private,algorithm='RS256',headers=headers or {'kid':'issuer-1','typ':'at+jwt'})
    return replace(settings,oidc_file=path,reviewer_file=reviewers),token,config,path,reviewers


def test_oidc_access_token_review_and_immediate_revocation(settings,tmp_path):
    settings,token,config,path,reviewers=issuer(settings,tmp_path)
    with TestClient(create_app(settings),base_url=settings.origin) as client:
        gate=client.app.state.gate; pending=gate.submit(call())
        auth=lambda t:{'Authorization':'Bearer '+t}
        agent=token('agent-service',roles=['operator','reviewer'])
        assert client.post('/v1/actions/'+pending['id']+'/decision',headers=auth(agent),json=decision(pending).model_dump()).status_code==403
        assert count(gate)==1206
        reviewer=token()
        assert client.post('/v1/policy/reload',headers=auth(reviewer)).status_code==403
        assert client.post('/v1/actions/'+pending['id']+'/decision',headers=auth(reviewer),json=decision(pending).model_dump()).json()['state']=='executed'
        assert count(gate)==1205 and gate.store.verify_audit()['valid']
        config['subjects'].pop('review-human');path.write_text(json.dumps(config))
        assert client.get('/v1/me',headers=auth(reviewer)).status_code==401
        config['subjects']['review-human']='reviewer:oidc';path.write_text(json.dumps(config))
        data=json.loads(reviewers.read_text());data['reviewers'][0]['active']=False;reviewers.write_text(json.dumps(data))
        assert client.get('/v1/me',headers=auth(reviewer)).status_code==401


@pytest.mark.parametrize('bad', ['audience','issuer','expired','future','lifetime','id_token','key_url','unknown_key','revoked','forged'])
def test_oidc_rejects_confused_or_untrusted_tokens(settings,tmp_path,bad):
    settings,token,config,path,_=issuer(settings,tmp_path)
    overrides={'audience':{'aud':'https://upstream.example'},'issuer':{'iss':'https://evil.invalid'},
        'expired':{'exp':int(time.time())-1},'future':{'iat':int(time.time())+100},
        'lifetime':{'exp':int(time.time())+90000},'revoked':{'jti':'revoked-token'}}
    headers={'id_token':{'kid':'issuer-1','typ':'JWT'},'key_url':{'kid':'issuer-1','typ':'at+jwt','jku':'https://evil.invalid'},
        'unknown_key':{'kid':'other','typ':'at+jwt'}}
    if bad=='revoked':config['revoked_jti']=['revoked-token'];path.write_text(json.dumps(config))
    value=token(headers=headers.get(bad),**overrides.get(bad,{}))
    if bad=='forged':value=value.rsplit('.',1)[0]+'.'+('x'*342)
    with TestClient(create_app(settings),base_url=settings.origin) as client:
        result=client.get('/v1/me',headers={'Authorization':'Bearer '+value})
        assert result.status_code==401 and value not in result.text
