import pytest
from fastapi.testclient import TestClient
from airlock.models import Settings, Invocation, Decision
from airlock.service import Gate
from airlock.api import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "test.db", "agent-" + "a" * 32, "reviewer-" + "b" * 32, "audit-" + "c" * 32)


@pytest.fixture
def gate(settings):
    return Gate(settings)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), base_url=settings.origin) as client:
        yield client


def call(sql="DELETE FROM customers WHERE id=1", key="test-key-001", parameters=None, **kwargs):
    return Invocation(sql=sql, idempotency_key=key, parameters=parameters or [], **kwargs)


def decision(action, value="approve", **kwargs):
    return Decision(decision=value, review_digest=action["review_digest"], expected_version=action["version"],
                    reason="Reviewed the exact impact", confirmation=action["confirmation_required"], **kwargs)


def count(gate):
    with gate.store.connection() as conn:
        return conn.execute("SELECT count(*) FROM customers").fetchone()[0]
