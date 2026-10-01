# 仕様: docs/spec/update-notification.md
"""起動時に1回だけ、GitHub Releases で公開されている最新の版を確認する。"""
import json
import re
import threading
import urllib.request

from . import state

try:
    # リリースのビルドで、タグから作られる（開発時の実行には無い）
    from ._build_version import APP_VERSION
except ImportError:
    APP_VERSION = None

RELEASES_API_URL = "https://api.github.com/repos/yuki-untitled/omnishot/releases/latest"
# 開く先は、このリポジトリのリリースのページだけに限る（応答の内容が書き換えられていても、別のサイトを開かない）
RELEASE_PAGE_PREFIX = "https://github.com/yuki-untitled/omnishot/"
TIMEOUT_SECONDS = 10.0

_VERSION_PATTERN = re.compile(r'v?(\d+)\.(\d+)\.(\d+)')


def parse_version(text):
    """"v1.3.1" を (1, 3, 1) にする。読み取れなければ None。"""
    match = _VERSION_PATTERN.fullmatch(text.strip()) if isinstance(text, str) else None
    return tuple(int(part) for part in match.groups()) if match else None


def _fetch_latest_release():
    request = urllib.request.Request(RELEASES_API_URL, headers={
        "Accept": "application/vnd.github+json",
        # GitHub の API は User-Agent が必須。送るのはアプリ名と版だけ
        "User-Agent": f"OmniShot/{APP_VERSION}",
    })
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def find_update(current_version, fetch=None):
    """現在の版より新しい版が公開されていれば {"latest", "current", "url"} を返す。無い・確認に失敗したときは None。"""
    current = parse_version(current_version)
    if current is None:
        return None
    try:
        release = (fetch or _fetch_latest_release)()
        latest = parse_version(release.get("tag_name"))
        url = release.get("html_url")
        # 下書き・先行版は、最新の版として扱わない
        if (latest is None or release.get("draft") or release.get("prerelease")
                or not isinstance(url, str) or not url.startswith(RELEASE_PAGE_PREFIX)):
            return None
    except Exception:
        return None
    if latest <= current:
        return None
    return {"latest": release["tag_name"], "current": current_version, "url": url}


def _run_check():
    update = find_update(APP_VERSION)
    state.update_info = {"status": "available", **update} if update else {"status": "none"}


def start_background():
    """配布版のときだけ、確認を別のスレッドで1回始める。開発時の実行では何もしない。"""
    if APP_VERSION is None:
        return
    state.update_info = {"status": "checking"}
    threading.Thread(target=_run_check, daemon=True).start()
