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
    assert "6" in resp.text


def test_healthz_returns_ok(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_index_page_loads_scripts_in_correct_order(client):
    resp = client.get("/")
    html = resp.text
    map_js_pos = html.find('/static/map.js')
    reports_js_pos = html.find('/static/reports.js')
    report_form_js_pos = html.find('/static/report-form.js')
    assert map_js_pos != -1, "map.js script tag not found"
    assert reports_js_pos != -1, "reports.js script tag not found"
    assert report_form_js_pos != -1, "report-form.js script tag not found"
    assert map_js_pos < reports_js_pos, "map.js must load before reports.js (reports.js reads window.mywaterMap at top level)"


def test_static_stylesheet_served_correctly(client):
    resp = client.get("/static/style.css")
    assert resp.status_code == 200
    assert "text/css" in resp.headers["content-type"]


def test_static_map_js_served_correctly(client):
    resp = client.get("/static/map.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]
