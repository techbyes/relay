def test_invalid_key_is_rejected(client):
    test_client, _ = client
    resp = test_client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": "Bearer sk-does-not-exist"},
    )
    assert resp.status_code == 401


def test_missing_auth_header_is_rejected(client):
    test_client, _ = client
    resp = test_client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code in (401, 422)


def test_inactive_key_is_rejected(client):
    from app.models import ApiKey

    test_client, session_factory = client
    db = session_factory()
    db.add(ApiKey(virtual_key="sk-relay-inactive", name="test", is_active=False))
    db.commit()
    db.close()

    resp = test_client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": "Bearer sk-relay-inactive"},
    )
    assert resp.status_code == 401
