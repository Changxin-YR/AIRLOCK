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
