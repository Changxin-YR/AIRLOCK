"""Execute frozen dirty-worktree counterchecks with a clean synthetic environment."""
from pathlib import Path
import json,subprocess,sys,tempfile,zipfile

root=Path.cwd();out=root/'var/startup-preflight-20261004/independent-retest'
label=sys.argv[1] if len(sys.argv)>1 else 'first'
result=out/label;result.mkdir(exist_ok=False)
with tempfile.TemporaryDirectory(prefix='airlock-preflight-retest-') as location:
    isolated=Path(location);source=isolated/'source';source.mkdir()
    with zipfile.ZipFile(out/(label+'-source.zip')) as archive:
        for name in archive.namelist():
            assert (source/name).resolve().is_relative_to(source.resolve())
        archive.extractall(source)
    config=isolated/'pytest.ini';config.write_text('[pytest]\naddopts =\n')
    environment={'SystemRoot':r'C:\Windows','TEMP':str(isolated),'TMP':str(isolated),
        'PYTHONPATH':str(source),'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1',
        'COUNTERCHECK_OUTPUT':str(result),'COUNTERCHECK_SOURCE':str(source),
        'PLAYWRIGHT_BROWSERS_PATH':r'C:\Users\27363\AppData\Local\ms-playwright'}
    command=[sys.executable,'-m','pytest','-q','-rA','-c',str(config),'--rootdir',str(isolated),
       '--junitxml='+str(result/'pytest.xml'),str(out/'test_countercheck.py')]
    done=subprocess.run(command,cwd=isolated,env=environment,capture_output=True,timeout=150)
    (result/'stdout.log').write_bytes(done.stdout);(result/'stderr.log').write_bytes(done.stderr)
    (result/'child-status.json').write_text(json.dumps({'command':command,'child_exit_code':done.returncode,
          'source_snapshot':label+'-source.zip','scope':'isolated synthetic environment; no host credentials or databases'},indent=2)+'\n')
    sys.stdout.buffer.write(done.stdout);sys.stderr.buffer.write(done.stderr)
    raise SystemExit(done.returncode)
