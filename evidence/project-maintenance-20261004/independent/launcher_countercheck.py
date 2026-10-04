from pathlib import Path
import json,subprocess,tempfile,sys
root=Path.cwd();python=Path(sys.executable).resolve();rows=[]
with tempfile.TemporaryDirectory(prefix='airlock-launcher-check-') as temp:
 p=Path(temp);folder=p/'directory';folder.mkdir();bad=p/'invalid.json';bad.write_text('{"AIRLOCK_AGENT_TOKEN":"fixture-sensitive-marker",',encoding='utf-8');array=p/'array.json';array.write_text('[]');typed=p/'typed.json';typed.write_text('{"AIRLOCK_AGENT_TOKEN":"fixture-sensitive-marker","AIRLOCK_AUDIT_KEY":42}')
 environment={'SystemRoot':r'C:\Windows','TEMP':temp,'TMP':temp,'AIRLOCK_AGENT_TOKEN':'fixture-agent-'+'a'*32,'AIRLOCK_REVIEWER_TOKEN':'fixture-reviewer-'+'r'*32,'AIRLOCK_AUDIT_KEY':'fixture-audit-'+'k'*32,'AIRLOCK_DB':str(p/'must-not-open.sqlite')}
 cases=[('missing',str(p/'missing.json')),('directory',str(folder)),('invalid_json',str(bad)),('non_object',str(array)),('non_string',str(typed)),('empty','')]
 for name,path in cases:
  done=subprocess.run([str(python),'-m','airlock','serve','--config',path],cwd=root,env=environment,timeout=8,capture_output=True,text=True)
  assert done.returncode==2,(name,done.returncode)
  assert 'readable regular UTF-8 JSON file' in done.stderr
  assert 'fixture-sensitive-marker' not in done.stderr+done.stdout
  assert not (p/'must-not-open.sqlite').exists()
  rows.append({'case':name,'exit_code':done.returncode,'database_created':False,'stderr_sanitized':True})
 done=subprocess.run([str(python),'-m','airlock','--help'],cwd=root,env=environment,timeout=8,capture_output=True,text=True)
 assert done.returncode==0 and 'Airlock local service' in done.stdout
 rows.append({'case':'help','exit_code':done.returncode})
print(json.dumps({'status':'PASS','checks':rows,'scope':'Independent real child-process CLI checks with only synthetic environment values; no server or existing DB opened.'}))
