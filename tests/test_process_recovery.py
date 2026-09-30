from __future__ import annotations

import os
import subprocess
import sys

from conftest import approve, log_in, review_request, submit
from process_helpers import ROOT

from airlock.common import now_ms
from airlock.storage import jobs


def test_actual_process_dies_after_target_commit_then_receipt_recovers(system, tmp_path):
    headers = log_in(system)
    op = submit(system, review_request())
    system["service"].tick()
    assert approve(system, op, headers).status_code == 200
    script = """
import os
from pathlib import Path
from airlock.config import ConfigSource
from airlock.storage import Store
from airlock.target import SQLiteTarget
from airlock.runner import LocalRunner
from airlock.service import ReviewService
source=ConfigSource(os.environ['AIRLOCK_CONFIG'])
config=source.read()
target=SQLiteTarget(Path(config.meta_path).parent.parent/'runner/target.db',config.runner_secret)
class CommitAndDie(LocalRunner):
    def execute(self,plan):
        super().execute(plan)
        os._exit(88)
service=ReviewService(Store(config.meta_path),source,CommitAndDie(target,config.policy_path))
service.tick()
"""
    env = {**os.environ, "AIRLOCK_CONFIG": str(system["config_path"]), "PYTHONPATH": str(ROOT)}
    child = subprocess.run(
        [sys.executable, "-c", script], env=env, cwd=ROOT, capture_output=True, timeout=15
    )
    assert child.returncode == 88, child.stderr.decode()
    assert system["service"].get_for_agent(system["principal"], op["id"])["state"] == "EXECUTING"
    with system["target"].connection() as conn:
        assert conn.execute("select count(*) from execution_receipts").fetchone()[0] == 1
        assert conn.execute("select count(*) from customers where tag='已核验'").fetchone()[0] == 6
    # Controlled test clock advance for the abandoned lease; production waits lease_until.
    with system["store"].transaction() as conn:
        conn.execute(
            jobs.update().where(jobs.c.operation_id == op["id"]).values(lease_until=now_ms() - 1)
        )
    clean_script = (
        script[: script.index("class CommitAndDie")]
        + """
service=ReviewService(Store(config.meta_path),source,LocalRunner(target,config.policy_path))
service.tick()
"""
    )
    restarted = subprocess.run(
        [sys.executable, "-c", clean_script], env=env, cwd=ROOT, capture_output=True, timeout=15
    )
    assert restarted.returncode == 0, restarted.stderr.decode()
    assert system["service"].get_for_agent(system["principal"], op["id"])["state"] == "SUCCEEDED"
    with system["target"].connection() as conn:
        assert conn.execute("select count(*) from execution_receipts").fetchone()[0] == 1
    assert system["store"].audit_log(op["id"])["events"][-1]["kind"] == "RECEIPT_RECOVERED"
    print(
        "PROCESS_RECOVERY: child exit=88 after commit; new process reconciled; one receipt; six changed records"
    )
