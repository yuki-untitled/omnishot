# 仕様: docs/spec/bugs/LOCAL-047_Windowsで絵文字を含むログの出力で起動直後にアプリが落ちる.md
import io
import sys

from omnishot import logs


def _cp932_stdout():
    return io.TextIOWrapper(io.BytesIO(), encoding="cp932", errors="strict")


def test_cp932で絵文字を含むログを追加しても例外にならずログ欄には絵文字が残る(monkeypatch):
    out = _cp932_stdout()
    monkeypatch.setattr(sys, "stdout", out)
    logs.add_log("🚀 OmniShot を起動中...")
    assert "🚀" in logs.log_queue[-1][1]
    out.flush()
    assert b"?" in out.buffer.getvalue()


def test_出力先がなくても例外にならない(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    logs.add_log("🚀 起動")


def test_utf8では絵文字がそのまま出力される(monkeypatch):
    out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    monkeypatch.setattr(sys, "stdout", out)
    logs.safe_print("🚀 起動")
    out.flush()
    assert "🚀".encode("utf-8") in out.buffer.getvalue()


def test_終了処理とポート案内の出力もcp932で例外にならない(monkeypatch):
    monkeypatch.setattr(sys, "stdout", _cp932_stdout())
    from omnishot import port_guard
    monkeypatch.setattr(port_guard.platform, "system", lambda: "Linux")
    port_guard.show_port_in_use_dialog(5001)
