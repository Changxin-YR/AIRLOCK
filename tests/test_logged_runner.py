import json
from pathlib import Path
import subprocess
import sys
import pytest


@pytest.mark.parametrize('code',[0,23])
def test_logged_runner_preserves_exit_code(tmp_path,code):
    log=tmp_path/'command.log'
    result=subprocess.run([sys.executable,'scripts/run_logged.py',str(log),'--',sys.executable,'-c',
                           f"print('child output'); raise SystemExit({code})"],capture_output=True,timeout=10)
    assert result.returncode==code
    assert b'child output' in log.read_bytes()
    assert json.loads(log.with_suffix('.log.status.json').read_text())['exit_code']==code


def test_logged_runner_missing_command_is_failure(tmp_path):
    log=tmp_path/'missing.log'
    result=subprocess.run([sys.executable,'scripts/run_logged.py',str(log),'--',str(tmp_path/'missing-executable')],capture_output=True,timeout=10)
    assert result.returncode==127
    assert json.loads(log.with_suffix('.log.status.json').read_text())['exit_code']==127


@pytest.mark.parametrize('changed,expected_dirty', [('validate_matrix.py',True),('REPORT.md',False)])
def test_logged_runner_distinguishes_executable_acceptance_from_reports(tmp_path,changed,expected_dirty):
    runner=Path('scripts/run_logged.py').resolve()
    def git(*args):
        return subprocess.run(['git',*args],cwd=tmp_path,capture_output=True,check=True)
    git('init','--quiet')
    folder=tmp_path/'docs/acceptance';folder.mkdir(parents=True)
    for name in ('validate_matrix.py','REPORT.md'):(folder/name).write_text('baseline\n')
    git('add','docs')
    git('-c','user.name=Isolated Test','-c','user.email=fixture@example.invalid','commit','--quiet','-m','fixture')
    (folder/changed).write_text('modified\n')
    log=tmp_path/'result.log'
    result=subprocess.run([sys.executable,str(runner),str(log),'--',sys.executable,'-c','print("fixture only")'],
                          cwd=tmp_path,capture_output=True,timeout=10)
    assert result.returncode==0
    receipt=json.loads(log.with_suffix('.log.status.json').read_text())
    assert receipt['tracked_source_dirty'] is expected_dirty
    assert receipt['tested_commit_sha']==git('rev-parse','HEAD').stdout.decode().strip()
