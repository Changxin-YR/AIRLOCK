"""Native Next.js browser counterexamples against an isolated real HTTP gate.

Faults are deliberate: a new trigger after preview, server clock advancement,
and an independent upstream that commits then drops the response. No action
state is written by the test. Automated reviewers are not human participants.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
import uvicorn
from airlock.api import create_app
from airlock.models import Settings
from scripts.support import ROOT,stop_process_tree


def free_port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]


async def run(output):
    from playwright.async_api import async_playwright
    output.mkdir(parents=True,exist_ok=True);checks=[];errors=[];violations=[]
    with tempfile.TemporaryDirectory(prefix='airlock-ui-edges-') as directory:
        root=Path(directory);port=free_port();remote_port=free_port();url=f'http://127.0.0.1:{port}'
        remote_key=secrets.token_urlsafe(32)
        # Dedicated fixture credential; no production provider/reviewer variables.
        env={k:v for k,v in os.environ.items() if k in {'PATH','SYSTEMROOT','WINDIR','TEMP','TMP'}}
        env.update(AIRLOCK_UPSTREAM_TEST_TOKEN=remote_key,AIRLOCK_TEST_DROP_RESPONSE='1')
        remote=subprocess.Popen([sys.executable,str(ROOT/'scripts/fixture_upstream.py'),'--port',str(remote_port),'--database',str(root/'remote.db')],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        upstream=root/'upstream.json'
        # This fixture runs in the server process and uses a unique variable.
        name='AIRLOCK_UPSTREAM_BROWSER_FIXTURE';old=os.environ.get(name);os.environ[name]=remote_key
        upstream.write_text(json.dumps({'tools':[{'name':'upstream:counter','resource':'synthetic:counter',
            'url':f'http://127.0.0.1:{remote_port}','credential_env':name,'allow_loopback':True,'arguments':{'delta':'integer'}}]}))
        settings=Settings(root/'gate.db',secrets.token_urlsafe(32),secrets.token_urlsafe(32),secrets.token_urlsafe(32),origin=url,upstream_file=upstream)
        app=create_app(settings);gate=app.state.gate;clock=[time.time()];gate.clock=lambda:clock[0]
        service=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error',access_log=False))
        thread=threading.Thread(target=service.run,daemon=True);thread.start()
        try:
            with httpx.Client(base_url=url,trust_env=False,timeout=5) as client:
                agent={'Authorization':'Bearer '+settings.agent_token};reviewer={'Authorization':'Bearer '+settings.reviewer_token}
                for _ in range(100):
                    try:
                        if client.get('/healthz').status_code==200:break
                    except httpx.HTTPError:pass
                    await asyncio.sleep(.05)
                else:raise RuntimeError('HTTP startup')
                with httpx.Client(trust_env=False,timeout=2) as probe:
                    for _ in range(100):
                        try:
                            if probe.get(f'http://127.0.0.1:{remote_port}/state',headers={'Authorization':'Bearer '+remote_key}).status_code==200:break
                        except httpx.HTTPError:pass
                        await asyncio.sleep(.05)
                    else:raise RuntimeError('upstream startup')
                def submit(key,**body):
                    r=client.post('/v1/actions',headers=agent,json=body|{'idempotency_key':key});r.raise_for_status();return r.json()
                def approve(a):
                    detail=client.get('/v1/actions/'+a['id'],headers=reviewer).json()
                    r=client.post('/v1/actions/'+a['id']+'/decision',headers=reviewer,json={'decision':'approve','reason':'Independent automated fixture approval','review_digest':detail['review_digest'],'expected_version':detail['version'],'confirmation':detail['confirmation_required']});r.raise_for_status();return r.json()
                async with async_playwright() as p:
                    browser=await p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH'),args=['--no-sandbox'])
                    page=await browser.new_page(viewport={'width':1280,'height':1000})
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.on('console',lambda m:violations.append(m.text) if 'Content Security Policy' in m.text else None)
                    await page.goto(url);await page.locator('#credential').fill(settings.reviewer_token)
                    await page.locator('#credential').press('Tab');assert await page.locator('#login-button').evaluate('(e)=>e===document.activeElement')
                    await page.keyboard.press('Enter');await page.get_by_role('button',name='退出',exact=True).wait_for()
                    async def select(a):
                        await page.get_by_role('button',name='执行记录',exact=True).click()
                        await page.get_by_role('button',name='刷新',exact=True).click()
                        await page.locator('[data-action="'+a['id']+'"]').click()
                    async def browser_approve():
                        await page.locator('#reason').fill('已核验本次独立测试的变更授权')
                        await page.locator('#ack').check();await page.locator('#approve').click()
                    stale=submit('browser-edge-stale',sql='UPDATE customers SET balance=balance+1 WHERE id=2')
                    other=submit('browser-edge-other',sql='UPDATE customers SET balance=balance+1 WHERE id=3');approve(other)
                    await select(stale);await browser_approve();await page.locator('.outcome.stale').wait_for();checks.append('stale_cas_never_overwrites_new_data')
                    failed=submit('browser-edge-failed',sql='UPDATE customers SET balance=balance+1 WHERE id=4')
                    with gate.store.transaction() as conn:conn.execute("CREATE TRIGGER fail_write BEFORE UPDATE ON customers BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
                    await select(failed);await browser_approve();await page.locator('.outcome.failed').wait_for()
                    with gate.store.transaction() as conn:
                        assert conn.execute('SELECT balance FROM customers WHERE id=4').fetchone()[0]==1000
                        conn.execute('DROP TRIGGER fail_write')
                    checks.append('execution_failure_rolls_back_and_renders')
                    remote_action=submit('browser-edge-unknown',tool='upstream:counter',arguments={'delta':3})
                    await select(remote_action);await browser_approve();await page.locator('.outcome.unknown').wait_for()
                    assert await page.locator('#approve').count()==0
                    r=client.post('/v1/actions/'+remote_action['id']+'/reconcile',headers=agent);assert r.json()['state']=='executed'
                    await page.get_by_role('button',name='刷新',exact=True).click();await page.locator('.outcome.executed').wait_for()
                    checks.append('unknown_requires_original_receipt_reconciliation')
                    xss="<img src=x onerror=alert(1)>"
                    injected=submit('browser-edge-xss',sql='UPDATE customers SET name=? WHERE id=5 /*'+'长文本'*150+'*/',parameters=[xss])
                    assert injected['state']=='pending'
                    await select(injected);assert await page.locator('.detail img').count()==0
                    await page.set_viewport_size({'width':390,'height':844})
                    assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    await page.screenshot(path=str(output/'edges-mobile.png'),full_page=True)
                    checks.append('untrusted_long_text_is_escaped_and_mobile_bounded')
                    # The real server expiry path uses the advanced test clock.
                    clock[0]+=301
                    await page.get_by_role('button',name='刷新',exact=True).click();await page.locator('.outcome.expired').wait_for()
                    assert await page.locator('#approve').count()==0;checks.append('expired_action_has_no_decision_controls')
                    blocked=submit('browser-edge-blocked',sql='DROP TABLE customers');await select(blocked)
                    await page.locator('.outcome.blocked').wait_for();assert await page.locator('#approve').count()==0
                    checks.append('hard_block_has_no_override_controls')
                    assert client.get('/v1/metrics',headers=reviewer).json()['customers']==1206
                    assert client.get('/v1/audit/verify',headers=reviewer).json()['valid']
                    await page.get_by_role('button',name='退出',exact=True).click();await page.reload()
                    assert await page.locator('#credential').input_value()==''
                    assert await page.evaluate('localStorage.length===0 && sessionStorage.length===0')
                    checks.append('keyboard_login_and_logout_clear_memory_credentials')
                    assert not errors and not violations,(errors,violations)
                    checks.append('next_hydration_and_strict_csp_have_no_errors')
                    await browser.close()
        finally:
            service.should_exit=True;thread.join(10);stop_process_tree(remote)
            if old is None:os.environ.pop(name,None)
            else:os.environ[name]=old
    report={'mode':'native_next_browser_real_http','passed':checks,'errors':errors,'csp_violations':violations,'human_participants':0}
    (output/'browser-edges.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'evidence');args=parser.parse_args();asyncio.run(run(args.output))
