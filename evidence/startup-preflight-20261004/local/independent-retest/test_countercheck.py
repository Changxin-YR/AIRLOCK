"""Independent synthetic startup counterchecks. Never reads host credentials."""
from pathlib import Path
import base64
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
from unittest.mock import patch

import pytest

from airlock import api
from airlock.diagnostics import ConsoleValidationError, collect_checks, validate_console
from airlock.models import Settings

OUTPUT = Path(os.environ['COUNTERCHECK_OUTPUT'])
SOURCE = Path(os.environ['COUNTERCHECK_SOURCE'])
CREDENTIALS = {'AIRLOCK_AGENT_TOKEN': 'synthetic-agent-' + 'a'*32,
               'AIRLOCK_REVIEWER_TOKEN': 'synthetic-reviewer-' + 'r'*32,
               'AIRLOCK_AUDIT_KEY': 'synthetic-audit-' + 'k'*32}


def digest(text):
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() + "'"


def console_at(root, html='<html><body></body></html>', hashes=()):
    root.mkdir(parents=True)
    (root/'index.html').write_bytes(html.encode())
    (root/'csp.json').write_text(json.dumps({'script_hashes': list(hashes)}), encoding='utf-8')
    return root


def environment(root):
    return {'SystemRoot': r'C:\Windows', 'TEMP': str(root), 'TMP': str(root),
            'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(SOURCE),
            'AIRLOCK_DB': str(root/'not-created'/'fresh.sqlite'), **CREDENTIALS}


def execute(name, root, args, env):
    done = subprocess.run([sys.executable, '-m', 'airlock', *args], cwd=root, env=env,
                          capture_output=True, timeout=20)
    (OUTPUT/(name+'.stdout.log')).write_bytes(done.stdout)
    (OUTPUT/(name+'.stderr.log')).write_bytes(done.stderr)
    (OUTPUT/(name+'.status.json')).write_text(json.dumps({'command': ['python','-m','airlock',*args],
          'child_exit_code': done.returncode, 'stdout_sha256': hashlib.sha256(done.stdout).hexdigest(),
          'stderr_sha256': hashlib.sha256(done.stderr).hexdigest()}, indent=2)+'\n')
    return done


@pytest.mark.parametrize('key,value', [('AIRLOCK_TTL','synthetic-secret-numeric-marker'),
    ('AIRLOCK_ORIGIN','http://127.0.0.1:synthetic-secret-port-marker')])
def test_serve_real_subprocess_redacts_configuration(tmp_path,key,value):
    env=environment(tmp_path);env[key]=value
    done=execute('serve-'+key,tmp_path,['serve'],env)
    assert done.returncode == 2
    assert b'Traceback' not in done.stderr+done.stdout
    assert value.encode() not in done.stderr+done.stdout
    assert b'synthetic-secret-' not in done.stderr+done.stdout
    assert not (tmp_path/'not-created').exists()
    assert not (tmp_path/'var').exists()


@pytest.mark.parametrize('mode', ['bad_csp','missing_js','index_only','csp_only','entity_traversal','plain_traversal'])
@pytest.mark.parametrize('existing', [False, True])
def test_api_invalid_console_precedes_gate(tmp_path,monkeypatch,mode,existing):
    console=console_at(tmp_path/'console')
    if mode=='bad_csp': (console/'csp.json').write_text('{"script_hashes":"synthetic-invalid-marker"}')
    elif mode=='missing_js': (console/'index.html').write_text('<html><script src="/_next/missing.js"></script></html>')
    elif mode=='index_only': (console/'csp.json').unlink()
    elif mode=='csp_only': (console/'index.html').unlink()
    elif mode=='entity_traversal': (console/'index.html').write_text('<html><script src="/_next/&#46;&#46;/secret.js"></script></html>')
    elif mode=='plain_traversal': (console/'index.html').write_text('<html><script src="/_next/../secret.js"></script></html>')
    database=tmp_path/'database'/'sentinel.sqlite'
    if existing:
        database.parent.mkdir();database.write_bytes(b'SYNTHETIC-NOT-A-DATABASE\x00unchanged')
    settings=Settings(database, *CREDENTIALS.values())
    monkeypatch.setattr(api,'CONSOLE',console)
    with patch.object(api,'Gate',side_effect=AssertionError('Gate must not be constructed')) as gate:
        with pytest.raises(ValueError,match='console build is incomplete or invalid'):
            api.create_app(settings)
        gate.assert_not_called()
    if existing: assert database.read_bytes()==b'SYNTHETIC-NOT-A-DATABASE\x00unchanged'
    else: assert not database.parent.exists()
    assert list(tmp_path.rglob('*-wal'))==[] and list(tmp_path.rglob('*-shm'))==[]


def test_headless_liveness_compatibility(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(api,'CONSOLE',tmp_path/'missing-console')
    settings=Settings(tmp_path/'isolated.sqlite',*CREDENTIALS.values(),seed_rows=3)
    with TestClient(api.create_app(settings),base_url=settings.origin) as client:
        assert client.get('/healthz').status_code==200
        home=client.get('/')
        assert home.status_code==503 and home.json()['error']=='console_assets_missing'


@pytest.mark.parametrize('mode', ['config','environment','bad_config','bad_environment'])
def test_doctor_real_subprocess_is_read_only(tmp_path,mode):
    env=environment(tmp_path)
    args=['doctor','--json']
    if mode in {'config','bad_config'}:
        config=tmp_path/'synthetic.json'
        config.write_text(json.dumps(CREDENTIALS) if mode=='config' else '{"AIRLOCK_AGENT_TOKEN":"synthetic-private-json-marker",',encoding='utf-8')
        args+=['--config',str(config)]
        for key in CREDENTIALS: env.pop(key)
    if mode=='bad_environment': env['AIRLOCK_TTL']='synthetic-private-doctor-marker'
    # Sitecustomize registers Python audit guards before AIRLOCK imports.
    guard=tmp_path/'guard';guard.mkdir()
    (guard/'sitecustomize.py').write_text('''import atexit,json,os,sys
from pathlib import Path
attempts=[]
output=Path(os.environ['GUARD_RESULT'])
def audit(event,args):
 if event.startswith('socket.') and event not in {'socket.__new__'}:
  attempts.append(event);raise AssertionError('network access forbidden')
 if event=='sqlite3.connect' and args[0]!=':memory:':
  attempts.append('persistent_sqlite');raise AssertionError('persistent SQLite forbidden')
 if event=='open':
  name,mode,flags=args
  if isinstance(name,(str,bytes)) and Path(name)!=output and (flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND)):
   attempts.append('write');raise AssertionError('filesystem mutation forbidden')
 if event in {'os.mkdir','os.remove','os.rename','os.rmdir'}:
  attempts.append(event);raise AssertionError('filesystem mutation forbidden')
sys.addaudithook(audit)
atexit.register(lambda:output.write_text(json.dumps({'forbidden_attempts':attempts})))
''',encoding='utf-8')
    audit=tmp_path/'guard-result.json';env['GUARD_RESULT']=str(audit)
    env['PYTHONPATH']=str(guard)+os.pathsep+str(SOURCE)
    before={str(p.relative_to(tmp_path)):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    done=execute('doctor-'+mode,tmp_path,args,env)
    assert done.returncode==(0 if mode in {'config','environment'} else 2),done.stderr.decode()
    report=json.loads(done.stdout)
    assert report['status']==('PASS' if done.returncode==0 else 'FAIL')
    assert report['service_started'] is False
    assert {'persistent_database','remote_services','optional_integrations'}.issubset(report['not_checked'])
    assert b'synthetic-private-' not in done.stdout+done.stderr and b'Traceback' not in done.stdout+done.stderr
    assert json.loads(audit.read_text())=={'forbidden_attempts':[]}
    after={str(p.relative_to(tmp_path)):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file() and p!=audit}
    assert before==after
    assert not (tmp_path/'not-created').exists() and not (tmp_path/'var').exists()


def test_collect_checks_never_constructs_gate_store_or_reads_integrations(tmp_path):
    from airlock import service, store, semantic
    console=console_at(tmp_path/'console')
    env=environment(tmp_path)
    for key in ('AIRLOCK_POLICY_FILE','AIRLOCK_REVIEWER_FILE','AIRLOCK_OIDC_FILE','AIRLOCK_UPSTREAM_FILE',
                'AIRLOCK_SEMANTIC_FILE','AIRLOCK_AUDIT_KEY_FILE','AIRLOCK_AUDIT_ANCHOR_FILE'):
        env[key]=str(tmp_path/'must-not-read'/key)
    env['AIRLOCK_FUTURE_INTEGRATION']='synthetic-unvalidated-extension'
    env['AIRLOCK_OTLP_URL']='https://must-never-resolve.invalid/trace'
    original=sqlite3.connect;connections=[]
    def connect(database,*args,**kwargs):
        connections.append(database)
        assert database==':memory:'
        return original(database,*args,**kwargs)
    def deny(*args,**kwargs): raise AssertionError('unexpected side effect')
    with patch.object(service,'Gate',side_effect=deny),patch.object(store,'Store',side_effect=deny),\
         patch.object(semantic,'SemanticAdvisor',side_effect=deny),patch.object(sqlite3,'connect',side_effect=connect),\
         patch.object(socket,'create_connection',side_effect=deny),patch.object(socket,'getaddrinfo',side_effect=deny),\
         patch.object(socket.socket,'connect',side_effect=deny),patch.object(socket.socket,'connect_ex',side_effect=deny):
        report=collect_checks(env,console)
    assert report['status']=='PASS'
    assert connections==[':memory:']
    assert report['not_checked']==['persistent_database','remote_services','optional_integrations']
    assert not (tmp_path/'must-not-read').exists() and not (tmp_path/'not-created').exists()


def test_character_entities_in_asset_and_inline_body(tmp_path):
    body='window.entityProbe="&amp;&#13;";'
    root=console_at(tmp_path/'console','<html><script src="/_next/ent&#105;ty.js"></script><script>'+body+'</script></html>',[digest(body)])
    (root/'_next').mkdir();(root/'_next'/'entity.js').write_text('window.externalProbe=1;')
    assert validate_console(root)==[digest(body)]


@pytest.mark.parametrize('separator',['\r\n','\r'])
def test_noncanonical_raw_script_hash_is_rejected(tmp_path,separator):
    body='window.lineProbe=1;'+separator+'window.lineProbe=2;'
    root=console_at(tmp_path/'console','<html><script>'+body+'</script></html>',[digest(body)])
    with pytest.raises(ConsoleValidationError): validate_console(root)


@pytest.mark.parametrize('separator',['\r\n','\r'])
def test_browser_normalized_script_hash_is_accepted(tmp_path,separator):
    body='window.lineProbe=1;'+separator+'window.lineProbe=2;'
    expected=digest(body.replace('\r\n','\n').replace('\r','\n'))
    root=console_at(tmp_path/'console','<html><script>'+body+'</script></html>',[expected])
    assert validate_console(root)==[expected]


@pytest.mark.parametrize('kind',['asset','directory','root'])
def test_symlinks_do_not_escape_console(tmp_path,kind):
    outside=tmp_path/'outside';outside.mkdir();(outside/'payload.js').write_text('window.linkProbe=1;')
    root=console_at(tmp_path/'console','<html><script src="/_next/payload.js"></script></html>')
    try:
        if kind=='asset':
            (root/'_next').mkdir();(root/'_next'/'payload.js').symlink_to(outside/'payload.js')
        elif kind=='directory': (root/'_next').symlink_to(outside,target_is_directory=True)
        else:
            (root/'_next').mkdir();(root/'_next'/'payload.js').write_text('')
            link=tmp_path/'linked-console';link.symlink_to(root,target_is_directory=True);root=link
    except OSError as error:
        if kind=='asset':
            pytest.skip('ENVIRONMENT BLOCKED: synthetic file symlink unavailable, '+type(error).__name__)
        # Windows directory junctions are reparse points available without the
        # file-symlink privilege. Both paths belong to this fresh temp fixture.
        link=root/'_next' if kind=='directory' else tmp_path/'linked-console'
        target=outside if kind=='directory' else root
        quote=lambda value:"'"+str(value).replace("'","''")+"'"
        command='New-Item -ItemType Junction -Path '+quote(link)+' -Target '+quote(target)+' -ErrorAction Stop | Out-Null'
        result=subprocess.run([r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe',
                              '-NoProfile','-NonInteractive','-Command',command],capture_output=True,
                              env=environment(tmp_path),timeout=15)
        assert result.returncode==0,result.stderr.decode('utf-8','replace')
        if kind=='root': root=link
    with pytest.raises(ConsoleValidationError,match='console_unsafe_path'): validate_console(root)


def test_native_browser_confirms_crlf_hash_semantics(tmp_path):
    from playwright.sync_api import sync_playwright
    body='window.lineProbe=1;\r\nwindow.lineProbe=2;'
    html='<html><script>'+body+'</script></html>'
    results=[]
    with sync_playwright() as engine:
        browser=engine.chromium.launch(headless=True)
        try:
            for mode,hash_value,expected in [('raw',digest(body),None),('normalized',digest(body.replace('\r\n','\n')),2)]:
                context=browser.new_context(service_workers='block')
                def fulfill(route):
                    route.fulfill(status=200,headers={'content-type':'text/html; charset=utf-8',
                        'content-security-policy':"default-src 'none'; script-src "+hash_value},body=html)
                context.route('**/*',fulfill)
                page=context.new_page();logs=[]
                page.add_init_script("window.cspEvents=[];document.addEventListener('securitypolicyviolation',e=>window.cspEvents.push({directive:e.effectiveDirective,blockedURI:e.blockedURI}));")
                page.on('console',lambda message:logs.append({'type':message.type,'text':message.text}))
                page.goto('https://airlock-synthetic.invalid/');page.wait_for_load_state('networkidle')
                observed=page.evaluate('window.lineProbe ?? null')
                normalized=page.locator('script').text_content()
                events=page.evaluate('window.cspEvents')
                results.append({'mode':mode,'observed':observed,'script_text':normalized,'console':logs,'csp_events':events})
                assert observed==expected
                assert normalized==body.replace('\r\n','\n')
                assert (events==[]) if mode=='normalized' else any(e['directive']=='script-src-elem' and e['blockedURI']=='inline' for e in events)
                context.close()
        finally: browser.close()
    (OUTPUT/'browser-crlf.json').write_text(json.dumps(results,indent=2)+'\n')
