import pytest

import server


@pytest.fixture()
def client():
    server.app.config.update(TESTING=True)
    with server.app.test_client() as test_client:
        yield test_client


def test_health_endpoint_reports_runtime_dependencies(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert "ffmpeg" in payload
    assert "max_upload_mb" in payload


def test_host_allowlist_rejects_untrusted_hosts():
    assert server.host_allowed("https://www.youtube.com/watch?v=abc")
    assert server.host_allowed("https://music.youtube.com/watch?v=abc")
    assert not server.host_allowed("https://youtube.com.example.org/watch?v=abc")
    assert not server.host_allowed("file:///etc/passwd")
    assert not server.host_allowed("https://example.org/video")


def test_safe_name_removes_path_separators():
    name = server.safe_name("../../private/video?.mp4")
    assert "/" not in name
    assert "\\" not in name
    assert name


def test_info_rejects_non_youtube_host(client):
    response = client.post("/api/info", json={"url": "https://example.org/video"})
    assert response.status_code == 400
    assert "Only YouTube" in response.get_json()["error"]


def test_download_rejects_unsupported_format(client):
    response = client.post("/api/download", json={
        "url": "https://www.youtube.com/watch?v=abc",
        "mode": "video",
        "format": "exe",
        "quality": "1080",
    })
    assert response.status_code == 400
    assert "Unsupported video format" in response.get_json()["error"]


def test_new_job_rejects_when_queue_is_full(monkeypatch):
    monkeypatch.setattr(server, "MAX_ACTIVE_JOBS", 0)
    with pytest.raises(Exception) as exc:
        server.new_job("test", "queue-full")
    assert getattr(exc.value, "code", None) == 429
