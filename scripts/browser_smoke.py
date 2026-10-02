"""Native browser E2E by default. --bridge is explicitly a weaker transport fixture.

The fixture injects the SAME application JS/CSS into an offline page and forwards
fetch through HTTPX to the real local server, because this execution environment
blocks native localhost navigation. It does NOT verify native ES module loading,
CSP enforcement, redirects, browser networking or native SSE streaming.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.support import ROOT, server


async def run(bridge: bool, output: Path):
    import httpx
    from playwright.async_api import async_playwright
    output.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []
    with server() as (url, keys, client):
        agent = {'Authorization': 'Bearer ' + keys['AIRLOCK_AGENT_TOKEN']}
        reviewer = {'Authorization': 'Bearer ' + keys['AIRLOCK_REVIEWER_TOKEN']}
        def submit(sql, key):
            response = client.post('/v1/actions', headers=agent, json={'sql':sql, 'idempotency_key':key})
            response.raise_for_status()
            return response.json()
        small = submit('UPDATE customers SET balance=balance+1 WHERE id=1', 'browser-small')
        bulk = submit('DELETE FROM customers', 'browser-bulk')
        async with async_playwright() as p:
            executable = os.getenv('CHROMIUM_PATH')
            if not executable and Path('/usr/bin/chromium').exists():
                executable = '/usr/bin/chromium'
            browser = await p.chromium.launch(executable_path=executable, args=['--no-sandbox'])
            page = await browser.new_page(viewport={'width':1440, 'height':1100}, device_scale_factor=1)
            page.on('pageerror', lambda error: errors.append(str(error)))
            if bridge:
                async def fetch_fixture(source, path, options):
                    if not path.startswith('/v1/'):
                        raise ValueError('Fixture only supports application API routes.')
                    async with httpx.AsyncClient(base_url=url, trust_env=False, timeout=10) as transport:
                        if path.startswith('/v1/events'):
                            async with transport.stream('GET', path, headers=options.get('headers', {})) as response:
                                async for chunk in response.aiter_text():
                                    return {'status':response.status_code, 'body':chunk,
                                            'headers':{'Content-Type':'text/event-stream'}}
                        response = await transport.request(options.get('method','GET'), path,
                            headers=options.get('headers', {}), content=options.get('body'))
                        return {'status':response.status_code, 'body':response.text,
                                'headers':{'Content-Type':response.headers.get('content-type','application/json')}}
                await page.expose_binding('__airlockHttpFixture', fetch_fixture)
                await page.set_content('<!doctype html><html lang="zh-CN"><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="app"></div></body></html>')
                await page.add_style_tag(content=(ROOT/'airlock/static/style.css').read_text())
                await page.add_script_tag(content='''window.fetch=async (path,options={})=>{
                  if(options.signal?.aborted) throw new DOMException('Aborted','AbortError');
                  const result=await window.__airlockHttpFixture(String(path),{method:options.method||'GET',headers:options.headers||{},body:options.body});
                  return new Response(result.body,{status:result.status,headers:result.headers});
                };''')
                # Import removal is why this fixture is not a native module-loading test.
                source = '\n'.join(re.sub(r'^import .*?;\s*$', '', (ROOT/'airlock/static'/name).read_text(), flags=re.M)
                    .replace('export ', '') for name in ('lib.js','api.js','review.js','app.js'))
                await page.add_script_tag(type='module', content=source)
            else:
                await page.goto(url)
            await page.locator('#credential').fill(keys['AIRLOCK_AGENT_TOKEN'])
            await page.locator('#login-button').click()
            await page.get_by_text('此处仅接受审批人凭据', exact=False).wait_for()
            checks.append('agent_credential_rejected_by_reviewer_console')
            await page.locator('#credential').fill(keys['AIRLOCK_REVIEWER_TOKEN'])
            await page.locator('#login-button').click()
            await page.locator('#impact-summary').wait_for()
            assert await page.locator('#approve').is_disabled()
            checks.append('approval_disabled_without_informed_confirmation')
            await page.locator('#reason').fill('全表删除缺少业务授权，拒绝本次操作')
            await page.locator('#reject').click()
            await page.locator('.outcome.rejected').wait_for()
            assert client.get('/v1/actions/'+bulk['id'],headers=agent).json()['state'] == 'rejected'
            assert client.get('/v1/metrics',headers=reviewer).json()['customers'] == 1206
            checks.append('browser_rejection_preserves_all_1206_rows')
            await page.locator(f'[data-action="{small["id"]}"]').click()
            await page.locator('#reason').fill('已核验单行余额调整及业务授权')
            await page.locator('#ack').check()
            assert await page.locator('#approve').is_enabled()
            await page.locator('#approve').click()
            await page.locator('.outcome.executed').wait_for()
            verify = submit('SELECT balance FROM customers WHERE id=1', 'browser-verify')
            assert verify['result']['rows'] == [{'balance':1001}]
            checks.append('browser_approval_executes_real_update_once')
            latest = submit('DELETE FROM customers', 'browser-live')
            # Both modes consume the real server events; only native mode proves browser SSE.
            await page.locator(f'[data-action="{latest["id"]}"]').wait_for(timeout=10000)
            await page.locator(f'[data-action="{latest["id"]}"]').click()
            await page.locator('#reason').fill('核验本次高影响操作的授权范围')
            await page.locator('#ack').check()
            await page.locator('#confirmation').fill('EXECUTE 1')
            assert await page.locator('#approve').is_disabled()
            await page.locator('#confirmation').fill('EXECUTE 1206')
            assert await page.locator('#approve').is_enabled()
            checks.append('critical_action_requires_exact_1206_scope_phrase')
            await page.locator('#confirmation').fill('')
            await page.locator('#reason').fill('')
            await page.locator('#ack').uncheck()
            await page.locator('h1').click()
            await page.screenshot(path=str(output/'console-desktop.png'), full_page=True)
            await page.set_viewport_size({'width':390,'height':844})
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await page.screenshot(path=str(output/'console-mobile.png'), full_page=True)
            checks.append('390px_mobile_has_no_horizontal_overflow')
            await page.set_viewport_size({'width':1440,'height':1100})
            await page.get_by_role('button',name='审计回放',exact=True).click()
            await page.get_by_role('button',name='验证审计链',exact=True).click()
            await page.locator('.audit-verdict').wait_for()
            assert await page.locator('.audit-verdict').inner_text()
            checks.append('audit_replay_and_hmac_verification_render')
            await page.get_by_role('button',name='退出',exact=True).click()
            await page.locator('#credential').wait_for()
            checks.append('logout_removes_authenticated_console')
            assert not errors, errors
            checks.append('no_browser_javascript_errors')
            await browser.close()
    report={'mode':'dom_with_real_http_bridge' if bridge else 'native_browser_e2e',
            'passed':checks, 'errors':errors,
            'not_proven': ['native localhost navigation','ES module asset loading in browser','browser CSP enforcement','native streaming SSE'] if bridge else []}
    (output/'browser-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--bridge',action='store_true',help='Explicit weaker fixture; report records its limitations')
    parser.add_argument('--output',type=Path,default=ROOT/'evidence')
    args=parser.parse_args()
    asyncio.run(run(args.bridge,args.output))
