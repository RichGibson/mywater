def test_index_page_renders_map_container(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert '<div id="map">' in resp.text


def test_about_page_renders_anonymization_explanation(client):
    resp = client.get("/about")
    assert resp.status_code == 200
    assert "obscure" in resp.text.lower()
    assert "anonymiz" in resp.text.lower()


def test_healthz_returns_ok(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
