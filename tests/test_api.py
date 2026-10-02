import pytest
from conftest import call


def auth(token):
    return {"Authorization": "Bearer " + token}


def test_http_complete_flow(client, settings):
    agent, reviewer = auth(settings.agent_token), auth(settings.reviewer_token)
    response = client.post("/v1/actions", json=call().model_dump(), headers=agent)
    assert response.status_code == 202
    receipt = response.json()
    assert receipt["execution_occurred"] is False and "review_digest" not in receipt
    action = client.get("/v1/actions/" + receipt["id"], headers=reviewer).json()
    body = {"decision": "approve", "review_digest": action["review_digest"], "expected_version": 1,
            "reason": "Verified single row", "confirmation": ""}
    assert client.post(f"/v1/actions/{action['id']}/decision", json=body, headers=agent).status_code == 403
    assert client.post(f"/v1/actions/{action['id']}/decision", json=body, headers=reviewer).json()["state"] == "executed"
    assert client.get("/v1/actions/" + action["id"], headers=agent).json()["execution_occurred"]


@pytest.mark.parametrize("path", ["/v1/actions", "/v1/audit", "/v1/audit/verify", "/v1/metrics", "/v1/events"])
def test_anonymous_is_denied(client, path):
    assert client.get(path).status_code == 401


def test_client_cannot_inject_approval_or_identity(client, settings):
    for key in ("approved", "state", "principal", "risk", "reviewer", "impact"):
        payload = call().model_dump() | {key: "forged"}
        assert client.post("/v1/actions", json=payload, headers=auth(settings.agent_token)).status_code == 422


def test_cross_origin_decision_denied(client, settings):
    assert client.post("/v1/actions", json=call().model_dump(), headers=auth(settings.agent_token) | {
        "Origin": "https://evil.example"}).status_code == 403


def test_reviewer_cannot_submit_as_agent(client, settings):
    assert client.post("/v1/actions", json=call().model_dump(), headers=auth(settings.reviewer_token)).status_code == 403


def test_body_bounds(client, settings):
    response = client.post("/v1/actions", content=b"x" * 17000, headers=auth(settings.agent_token))
    assert response.status_code == 413


def test_static_security_headers(client):
    result = client.get("/")
    assert result.status_code == 200
    assert "unsafe-inline" not in result.headers["content-security-policy"]
    assert result.headers["x-content-type-options"] == "nosniff"


def test_credential_separation_is_mandatory(settings):
    from dataclasses import replace
    with pytest.raises(ValueError):
        replace(settings, reviewer_token=settings.agent_token)


def test_untrusted_host_denied(client):
    assert client.get('/healthz', headers={'Host':'evil.example'}).status_code == 400


def test_conflict_does_not_claim_previous_effect_never_happened(client, settings):
    agent = auth(settings.agent_token)
    client.post('/v1/actions', json=call('SELECT 1').model_dump(), headers=agent)
    response = client.post('/v1/actions', json=call('SELECT 2').model_dump(), headers=agent)
    assert response.status_code == 409 and response.json()['execution_occurred'] is None
