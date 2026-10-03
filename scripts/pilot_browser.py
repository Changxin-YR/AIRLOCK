"""Native browser checks for the independent pilot page and local alert inbox.

Fixtures use generated notification-only credentials and throwaway local state.
Browser automation is excluded from human study results.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import tempfile
from threading import Thread
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.pilot_server import Handler, ROOT


@contextmanager
def fixture_servers():
    import uvicorn
    from airlock.alert_inbox import create_app
    with tempfile.TemporaryDirectory(prefix='airlock-pilot-') as directory:
        with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as pilot, socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
            writer, reader = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            app = create_app(Path(directory) / 'inbox.sqlite3', write_token=writer, read_token=reader, port=port)
            service = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, access_log=False, log_level='error'))
            threads = [Thread(target=pilot.serve_forever, daemon=True),
                       Thread(target=lambda: service.run(sockets=[listener]), daemon=True)]
            for thread in threads:
                thread.start()
            try:
                for _ in range(100):
                    if service.started:
                        break
                    time.sleep(.05)
                else:
                    raise RuntimeError('inbox fixture did not start')
                yield f'http://127.0.0.1:{pilot.server_port}', f'http://127.0.0.1:{port}', writer, reader, Path(directory)
            finally:
                service.should_exit = True
                pilot.shutdown()
                for thread in threads:
                    thread.join(timeout=5)


async def run(output):
    from playwright.async_api import async_playwright
    from airlock.alert_delivery import AlertConfig, deliver_alerts
    from benchmark.research import study_report
    output.mkdir(parents=True, exist_ok=True)
    checks, errors, csp = [], [], []
    tasks = json.loads((ROOT / 'benchmark/pilot-github-tasks.json').read_text(encoding='utf-8'))['tasks']
    with fixture_servers() as (pilot_url, inbox_url, writer, reader, temporary):
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH'), args=['--no-sandbox'])
            page = await browser.new_page(viewport={'width': 1280, 'height': 960})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('console', lambda msg: csp.append(msg.text) if 'Content Security Policy' in msg.text else None)
            await page.goto(pilot_url)
            assert await page.title() == 'AIRLOCK 审批研究'
            await page.get_by_text('单人先导练习', exact=False).wait_for()
            await page.screenshot(path=str(output / 'pilot-desktop.png'), full_page=True)
            checks.append('pilot_public_assets_load_without_approval_service')
            await page.locator('#participant').fill('automation-pilot-check')
            await page.locator('#source').select_option('automation')
            await page.locator('#tasks').set_input_files(ROOT / 'benchmark/pilot-github-tasks.json')
            await page.locator('#consent').check()
            await page.locator('#start-study').click()
            for _ in tasks:
                text = await page.locator('#study-summary .sql').inner_text()
                task = next(task for task in tasks if task['sql'] == text)
                await page.locator('#study-' + task['gold']).click()
                await page.locator('#study-comprehension').select_option(task['check']['answer'])
                await page.locator('#study-check-submit').click()
            async with page.expect_download() as download:
                await page.locator('#export-study').click()
            await (await download.value).save_as(output / 'pilot-automation.json')
            session = json.loads((output / 'pilot-automation.json').read_text(encoding='utf-8'))
            assert len(session['responses']) == 8 and {r['arm'] for r in session['responses']} == {'A', 'B'}
            assert study_report([session])['human_participants'] == 0
            checks.append('eight_practice_decisions_exported_and_excluded_from_human_metrics')
            await page.set_viewport_size({'width': 390, 'height': 844})
            await page.goto(pilot_url)
            await page.locator('#start-study').wait_for()
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await page.screenshot(path=str(output / 'pilot-mobile.png'), full_page=True)
            checks.append('pilot_390px_no_horizontal_overflow')

            # This process owns only generated fixture credentials.
            os.environ['AIRLOCK_ALERT_WEBHOOK_TOKEN'] = writer
            config = AlertConfig(endpoint=inbox_url + '/airlock/events', allow_loopback_fixture=True)
            alert = {'status': 'alert', 'alerts': [{'code': 'audit_integrity_failed'}]}
            state = temporary / 'sender.sqlite3'
            assert deliver_alerts(config, alert, state)['status'] == 'delivered'
            assert deliver_alerts(config, alert, state)['status'] == 'unchanged'
            assert deliver_alerts(config, {'status': 'ok', 'alerts': []}, state)['status'] == 'delivered'
            os.environ.pop('AIRLOCK_ALERT_WEBHOOK_TOKEN')
            await page.set_viewport_size({'width': 1280, 'height': 960})
            await page.goto(inbox_url)
            await page.locator('#read-token').fill(reader)
            await page.locator('#login-form button[type=submit]').click()
            await page.locator('#events [data-event-id]').first.wait_for()
            assert await page.locator('#events [data-event-id]').count() == 2
            assert await page.evaluate('localStorage.length === 0 && sessionStorage.length === 0')
            assert reader not in page.url
            await page.screenshot(path=str(output / 'inbox-desktop.png'), full_page=True)
            checks.append('sender_alert_dedup_and_recovery_render_as_two_events')
            checks.append('inbox_read_token_not_in_url_or_browser_storage')
            await page.set_viewport_size({'width': 390, 'height': 844})
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await page.screenshot(path=str(output / 'inbox-mobile.png'), full_page=True)
            checks.append('inbox_390px_no_horizontal_overflow')
            await page.locator('#logout').click()
            assert await page.locator('#events [data-event-id]').count() == 0
            await page.locator('#login-form').wait_for()
            checks.append('inbox_logout_clears_authenticated_content')
            assert not errors and not csp
            checks.append('no_browser_javascript_or_csp_errors')
            await browser.close()
    report = {'status': 'PASS', 'mode': 'native_browser_e2e', 'browser_plugin': 'not available; project Playwright',
              'passed': checks, 'errors': errors, 'csp_violations': csp,
              'human_participants': 0, 'external_notifications': 0, 'business_side_effects': 0}
    (output / 'pilot-browser.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'evidence')
    asyncio.run(run(parser.parse_args().output))
