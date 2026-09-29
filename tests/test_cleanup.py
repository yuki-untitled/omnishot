# 仕様: docs/spec/bugs/LOCAL-042_起動時と終了時の後始末がアプリが作っていないファイルやプロセスに影響する.md
# 終了時の後始末（アプリが作ったものだけを消す）
import tempfile

from omnishot import cleanup


def test_cleanup_removes_only_capture_folder(tmp_path, monkeypatch):
    captures = tmp_path / "captures"
    captures.mkdir()
    (captures / "a.png").write_bytes(b"png")

    # 他のアプリのもの: OS の設定ファイル、一時フォルダの「ios」「adb」を含む名前のフォルダ
    home = tmp_path / "home"
    prefs = home / "Library" / "Preferences"
    prefs.mkdir(parents=True)
    plist = prefs / "com.apple.selfidentity.plist"
    plist.write_text("x")
    tmp = tmp_path / "tmp"
    (tmp / "my-ios-notes").mkdir(parents=True)
    (tmp / "adb-something").mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp))
    monkeypatch.setattr(cleanup, "SAVE_DIR", str(captures))

    cleanup._cleanup_temp_data()

    assert not captures.exists()
    assert plist.exists()
    assert (tmp / "my-ios-notes").is_dir() and (tmp / "adb-something").is_dir()
