# 仕様: docs/spec/bugs/LOCAL-042_起動時と終了時の後始末がアプリが作っていないファイルやプロセスに影響する.md
# 起動時のポート整理（前回の OmniShot だけを終了する）
import pytest

from omnishot import port_guard

NETSTAT = """
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:5001           0.0.0.0:0              LISTENING       4321
  TCP    127.0.0.1:5001         0.0.0.0:0              LISTENING       4321
  TCP    127.0.0.1:50011        0.0.0.0:0              LISTENING       999
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       5001
  TCP    127.0.0.1:52000        127.0.0.1:5001         ESTABLISHED     7777
  TCP    [::]:5001              [::]:0                 LISTENING       8888
"""


def test_parse_netstat_uses_listening_local_port_only():
    # 「5001」をプロセス番号やポートの一部に含む行、接続しているだけの行は対象にしない
    assert port_guard.parse_netstat_listening_pids(NETSTAT, 5001) == [4321, 8888]


@pytest.mark.parametrize("executable, command_line, expected", [
    ("/Users/a/OmniShot.app/Contents/MacOS/OmniShot", "", True),
    ("C:\\Users\\a\\Downloads\\OmniShot-v1.3.0-windows-x64.exe", "", True),
    ("OmniShot.exe", "", True),
    ("omnishot.exe", "", True),
    ("/usr/bin/python3", "python3 run.py", True),
    ("python.exe", "python.exe C:\\src\\omnishot\\run.py", True),
    ("/usr/bin/python3", "python3 -m http.server 5001", False),
    ("/usr/bin/python3", "python3 other/run2.py", False),
    ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "", False),
    ("", "", False),
])
def test_is_omnishot_process(executable, command_line, expected):
    assert port_guard.is_omnishot_process(executable, command_line) is expected


def _setup(monkeypatch, pids, infos):
    killed = []
    listening = {"pids": list(pids)}
    monkeypatch.setattr(port_guard, "listening_pids", lambda port: list(listening["pids"]))
    monkeypatch.setattr(port_guard, "process_info", lambda pid: infos[pid])

    def kill(pid):
        killed.append(pid)
        listening["pids"].remove(pid)
    monkeypatch.setattr(port_guard, "kill_process", kill)
    return killed


def test_free_port_kills_only_omnishot(monkeypatch):
    killed = _setup(monkeypatch, [1, 2], {1: ("/x/OmniShot", ""), 2: ("/usr/bin/python3", "python3 -m http.server 5001")})
    assert port_guard.free_port(5001) == [2]  # 別のアプリは終了せず、返す
    assert killed == [1]


def test_free_port_nothing_listening(monkeypatch):
    killed = _setup(monkeypatch, [], {})
    assert port_guard.free_port(5001) == []
    assert killed == []


def test_free_port_does_not_kill_other_apps(monkeypatch):
    killed = _setup(monkeypatch, [3], {3: ("/Applications/Other.app/Contents/MacOS/Other", "")})
    assert port_guard.free_port(5001) == [3]
    assert killed == []
