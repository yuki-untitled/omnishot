# 仕様: docs/spec/update-notification.md
# 起動時の新しい版の確認
import io
import json

import pytest

from omnishot import create_app, state, update_check

URL = "https://github.com/yuki-untitled/omnishot/releases/tag/v1.4.0"


def _release(tag="v1.4.0", draft=False, prerelease=False, url=URL):
    return lambda: {"tag_name": tag, "draft": draft, "prerelease": prerelease, "html_url": url}


@pytest.mark.parametrize("text, expected", [
    ("v1.3.1", (1, 3, 1)),
    ("1.3.1", (1, 3, 1)),
    (" v10.0.12 ", (10, 0, 12)),
    ("v1.3", None),
    ("v1.3.1-beta", None),
    ("latest", None),
    (None, None),
])
def test_parse_version(text, expected):
    assert update_check.parse_version(text) == expected


def test_finds_newer_release():
    assert update_check.find_update("v1.3.1", _release()) == {"latest": "v1.4.0", "current": "v1.3.1", "url": URL}


def test_numbers_are_compared_as_numbers_not_text():
    assert update_check.find_update("v1.9.0", _release("v1.10.0")) is not None
    assert update_check.find_update("v1.10.0", _release("v1.9.0")) is None


@pytest.mark.parametrize("current", ["v1.4.0", "v2.0.0"])
def test_same_or_older_release_is_not_notified(current):
    assert update_check.find_update(current, _release("v1.4.0")) is None


@pytest.mark.parametrize("kwargs", [{"draft": True}, {"prerelease": True}])
def test_draft_and_prerelease_are_ignored(kwargs):
    assert update_check.find_update("v1.3.1", _release(**kwargs)) is None


def test_release_page_outside_the_repository_is_ignored():
    assert update_check.find_update("v1.3.1", _release(url="https://example.com/evil")) is None


@pytest.mark.parametrize("error", [OSError("offline"), TimeoutError(), ValueError("bad json"), KeyError("x")])
def test_failure_is_silent(error):
    def fetch():
        raise error
    assert update_check.find_update("v1.3.1", fetch) is None


def test_unreadable_response_is_silent():
    assert update_check.find_update("v1.3.1", lambda: {"tag_name": None}) is None
    assert update_check.find_update("v1.3.1", lambda: []) is None


def test_development_run_makes_no_request(monkeypatch):
    monkeypatch.setattr(update_check, "APP_VERSION", None)
    monkeypatch.setattr(update_check, "_fetch_latest_release", lambda: pytest.fail("通信してはいけない"))
    update_check.start_background()
    assert state.update_info == {"status": "none"}


def test_background_check_stores_result(monkeypatch):
    monkeypatch.setattr(update_check, "APP_VERSION", "v1.3.1")
    monkeypatch.setattr(update_check, "_fetch_latest_release", _release())
    update_check._run_check()
    assert state.update_info == {"status": "available", "latest": "v1.4.0", "current": "v1.3.1", "url": URL}


def test_background_check_starts_once_in_a_thread(monkeypatch):
    monkeypatch.setattr(update_check, "APP_VERSION", "v1.3.1")
    started = []

    class FakeThread:
        def __init__(self, target, daemon):
            started.append((target, daemon))

        def start(self):
            pass

    monkeypatch.setattr(update_check.threading, "Thread", FakeThread)
    update_check.start_background()
    # 確認は別のスレッドで行い、起動を待たせない。結果が出るまでは「確認中」
    assert started == [(update_check._run_check, True)]
    assert state.update_info == {"status": "checking"}


def test_request_sends_only_app_name_and_version(monkeypatch):
    monkeypatch.setattr(update_check, "APP_VERSION", "v1.3.1")
    seen = {}

    def urlopen(request, timeout):
        seen.update(url=request.full_url, method=request.get_method(), data=request.data,
                    headers=dict(request.header_items()), timeout=timeout)
        return io.BytesIO(json.dumps({"tag_name": "v1.4.0"}).encode())

    monkeypatch.setattr(update_check.urllib.request, "urlopen", urlopen)
    assert update_check._fetch_latest_release() == {"tag_name": "v1.4.0"}
    assert seen["url"] == update_check.RELEASES_API_URL
    assert seen["method"] == "GET" and seen["data"] is None
    assert seen["timeout"] == 10.0
    assert seen["headers"]["User-agent"] == "OmniShot/v1.3.1"
    assert set(seen["headers"]) == {"Accept", "User-agent"}


# ---------------------------------------------------------------------------
# 画面からの要求
# ---------------------------------------------------------------------------
@pytest.fixture
def client(save_dir):
    app = create_app()
    app.testing = True
    return app.test_client()


def test_update_info_route(client):
    assert client.get("/update_info").get_json() == {"status": "none"}
    state.update_info = {"status": "available", "latest": "v1.4.0", "current": "v1.3.1", "url": URL}
    assert client.get("/update_info").get_json()["latest"] == "v1.4.0"


def test_dismiss_hides_notice_for_the_rest_of_the_run(client):
    state.update_info = {"status": "available", "latest": "v1.4.0", "current": "v1.3.1", "url": URL}
    client.post("/update_info/dismiss")
    assert client.get("/update_info").get_json() == {"status": "none"}


def test_open_uses_the_checked_url_in_the_default_browser(client, monkeypatch):
    opened = []
    monkeypatch.setattr("omnishot.routes.webbrowser.open", opened.append)
    state.update_info = {"status": "available", "latest": "v1.4.0", "current": "v1.3.1", "url": URL}
    # 開く先は画面から指定できない
    assert client.post("/update_info/open", json={"url": "https://example.com"}).status_code == 200
    assert opened == [URL]


def test_open_without_update_does_nothing(client, monkeypatch):
    opened = []
    monkeypatch.setattr("omnishot.routes.webbrowser.open", opened.append)
    assert client.post("/update_info/open").status_code == 404
    assert opened == []
