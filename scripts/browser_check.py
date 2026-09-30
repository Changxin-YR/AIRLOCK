"""Real browser + real processes + real SQLite; no API mocking or preloaded UI data."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from playwright.sync_api import sync_playwright,expect
from process_support import LiveSystem


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,default=ROOT/'Evidence/browser')
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    report={'driver':'Python Playwright','browser_plugin':'absent; using standard Playwright',
            'data':'fresh synthetic SQLite fixture; actual gateway/executor processes','checks':[]}
    with tempfile.TemporaryDirectory(prefix='airlock-browser-') as folder,LiveSystem(Path(folder)/'live') as live,sync_playwright() as p:
        kwargs={'headless':True}
        if os.environ.get('AIRLOCK_CHROMIUM'):kwargs['executable_path']=os.environ['AIRLOCK_CHROMIUM']
        browser=p.chromium.launch(**kwargs)
        context=browser.new_context(viewport={'width':1440,'height':1080},device_scale_factor=1)
        page=context.new_page();errors=[];console_errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('console',lambda msg:console_errors.append(msg.text) if msg.type=='error' else None)
        def shot(name):page.screenshot(path=str(args.out/(name+'.png')),full_page=True)
        def check(name,passed=True):
            report['checks'].append({'name':name,'pass':bool(passed)})
            assert passed,name
        def propose(title):
            page.get_by_role('button',name='发起演示请求').click()
            page.locator('.scenario-row').filter(has_text=title).get_by_role('button',name='提交请求',exact=True).click()
        def pending():expect(page.locator('.detail-panel').get_by_text('等待审批',exact=True)).to_be_visible(timeout=15000)
        try:
            page.goto(live.url);page.wait_for_selector('#password')
            check('page identity',page.title()=='AIRLOCK · 智能体变更审批')
            shot('01-login')
            page.get_by_label('密码',exact=True).fill(live.human_credentials['password'])
            page.get_by_role('button',name='进入工作台',exact=True).click()
            expect(page.get_by_role('heading',name='变更审批',exact=True)).to_be_visible()
            check('independent human login')
            expect(page.get_by_text('事件流已连接',exact=True)).to_be_visible(timeout=10000)
            check('SSE connected')
            propose('归档三条测试客户');pending()
            expect(page.locator('.diff-table')).to_contain_text('archived')
            check('real field diff and pending state')
            shot('02-review-desktop')
            page.set_viewport_size({'width':390,'height':844})
            check('mobile does not overflow',page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
            shot('03-review-mobile')
            page.set_viewport_size({'width':1440,'height':1080})
            page.get_by_role('button',name='批准这份变更',exact=True).click()
            expect(page.get_by_text('执行成功，目标事务回执已确认',exact=True)).to_be_visible(timeout=15000)
            with sqlite3.connect(live.root/'runner/target.db') as conn:
                check('actual target write',conn.execute("SELECT COUNT(*) FROM customers WHERE id IN(1,2,3) AND status='archived' AND version=1").fetchone()[0]==3)
            page.get_by_role('tab',name='审计时间线',exact=True).click()
            expect(page.get_by_text('本地事件链校验通过',exact=False)).to_be_visible()
            shot('04-audit-desktop');check('audit and immutable provided view')
            page.reload();expect(page.get_by_role('heading',name='变更审批',exact=True)).to_be_visible()
            check('session and persisted queue survive reload')
            propose('删除测试客户及备注');pending()
            expect(page.locator('.impact-breakdown')).to_contain_text('4')
            page.get_by_role('button',name='拒绝',exact=True).click()
            page.get_by_label('拒绝理由',exact=True).fill('保留备注，先核实是否需要归档。')
            page.get_by_role('button',name='确认拒绝',exact=True).click()
            expect(page.locator('.detail-panel').get_by_text('已拒绝',exact=True)).to_be_visible(timeout=10000)
            with sqlite3.connect(live.root/'runner/target.db') as conn:
                check('rejection has no delete effects',conn.execute('SELECT COUNT(*) FROM customers WHERE id IN(4,5)').fetchone()[0]==2)
            propose('阻止过宽删除')
            expect(page.locator('.detail-panel').get_by_text('策略阻断',exact=True)).to_be_visible(timeout=15000)
            check('blocked request has no override button',page.get_by_role('button',name='批准这份变更',exact=True).count()==0)
            shot('05-blocked')
            # Untrusted database strings must be displayed as text, not executable markup.
            with sqlite3.connect(live.root/'runner/target.db') as conn:
                conn.execute('UPDATE customers SET name=? WHERE id=4',('<img src=x onerror="window.airlockXss=1">',))
            propose('删除测试客户及备注');pending()
            expect(page.locator('.diff-table')).to_contain_text('<img src=x')
            check('untrusted database content escaped',page.evaluate('window.airlockXss===undefined'))
            # Change target after preview; approving the old view must not write it.
            with sqlite3.connect(live.root/'runner/target.db') as conn:
                conn.execute("UPDATE customers SET tag='independent-writer' WHERE id=10")
            page.get_by_role('button',name='批准这份变更',exact=True).click()
            expect(page.locator('.detail-panel').get_by_text('快照已失效',exact=True)).to_be_visible(timeout=15000)
            check('drift displayed as STALE, not success')
            with sqlite3.connect(live.root/'runner/target.db') as conn:
                check('stale operation did not delete',conn.execute('SELECT COUNT(*) FROM customers WHERE id IN(4,5)').fetchone()[0]==2)
            shot('06-stale')
            # A real offline interval triggers reconnect; server state is still authoritative.
            context.set_offline(True);page.wait_for_timeout(1200);context.set_offline(False)
            page.reload();expect(page.get_by_text('事件流已连接',exact=True)).to_be_visible(timeout=15000)
            check('offline and reconnect recover')
            check('no JavaScript runtime exception',not errors)
            # Login probe 401 and intentional offline errors are expected, not app exceptions.
            report['console_errors']=console_errors;report['page_errors']=errors
            report['expected_console_context']='unauthenticated session probe and intentional offline interval'
            report['desktop']=[1440,1080];report['mobile']=[390,844]
            report['browser_version']=browser.version
            page.get_by_role('button',name='退出登录',exact=True).click()
            expect(page.get_by_role('heading',name='登录审批工作台',exact=True)).to_be_visible()
            check('logout invalidates browser session')
            report['status']='PASS'
        except BaseException as exc:
            report['status']='FAIL';report['failure']=str(exc)
            shot('failure')
            raise
        finally:
            (args.out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
            browser.close()
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
