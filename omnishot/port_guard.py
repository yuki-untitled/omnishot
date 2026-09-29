# 仕様: docs/spec/bugs/LOCAL-042_起動時と終了時の後始末がアプリが作っていないファイルやプロセスに影響する.md
"""起動時に、前回の OmniShot が残したままのプロセスがポートを握っていれば終了する。

終了するのは、そのポートで待ち受けている（LISTEN している）プロセスのうち、OmniShot のものだけ。
ポートへ接続しているだけの側（ブラウザなど）や、別のアプリは終了しない。
"""
import os
import platform
import re
import subprocess
import time

from . import paths


def _run(cmd, timeout=5):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=paths.CREATE_NO_WINDOW)


def parse_netstat_listening_pids(output, port):
    """Windows の `netstat -ano -p TCP` の出力から、指定ポートで待ち受けているプロセスの番号を返す。

    ポート番号は、待ち受けのアドレス（「0.0.0.0:5001」の形）の末尾だけで比べる。
    プロセス番号などに「5001」を含む行は対象にしない。
    """
    pids = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING":
            if re.search(rf":{port}$", parts[1]) and parts[4].isdigit():
                pids.append(int(parts[4]))
    return list(dict.fromkeys(pids))


def is_omnishot_process(executable, command_line=""):
    """OmniShot のプロセスか。配布版は実行ファイル名が OmniShot で始まるもの、開発時は run.py を実行している Python。"""
    name = os.path.basename((executable or "").replace("\\", "/")).lower()
    if name.startswith("omnishot"):
        return True
    args = (command_line or "").replace("\\", "/").split()
    return "python" in name and any(os.path.basename(a) == "run.py" for a in args)


def listening_pids(port):
    """指定ポートで待ち受けているプロセスの番号を返す（自分自身は除く）。調べられなければ空。"""
    try:
        if platform.system() == "Windows":
            pids = parse_netstat_listening_pids(_run(["netstat", "-ano", "-p", "TCP"]).stdout, port)
        else:
            out = _run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"]).stdout
            pids = [int(p) for p in out.split() if p.isdigit()]
    except Exception:
        return []
    return [p for p in dict.fromkeys(pids) if p != os.getpid()]


def process_info(pid):
    """(実行ファイル, コマンドライン) を返す。調べられなければ ("", "")。"""
    try:
        if platform.system() == "Windows":
            name = _run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"]).stdout.strip().split(",")[0].strip('"')
            cmd = _run(["powershell", "-NoProfile", "-Command",
                        f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"]).stdout.strip()
            return name, cmd
        exe = _run(["ps", "-p", str(pid), "-o", "comm="]).stdout.strip()
        cmd = _run(["ps", "-p", str(pid), "-o", "command="]).stdout.strip()
        return exe, cmd
    except Exception:
        return "", ""


def kill_process(pid):
    try:
        if platform.system() == "Windows":
            _run(["taskkill", "/F", "/PID", str(pid)])
        else:
            os.kill(pid, 9)
    except Exception:
        pass


def free_port(port, wait_seconds=3.0):
    """前回の OmniShot がポートを握っていれば終了する。別のアプリが握っていれば終了せず、そのプロセスの番号を返す。

    戻り値: 別のアプリ（OmniShot 以外）のプロセスの番号のリスト。空ならポートを使える（または調べられなかった）。
    """
    blockers, stale = [], []
    for pid in listening_pids(port):
        executable, command_line = process_info(pid)
        (stale if is_omnishot_process(executable, command_line) else blockers).append(pid)
    for pid in stale:
        kill_process(pid)
    if stale:
        # 終了してポートが空くのを待つ
        deadline = time.time() + wait_seconds
        while time.time() < deadline and any(p in listening_pids(port) for p in stale):
            time.sleep(0.1)
    return blockers


def show_port_in_use_dialog(port):
    """別のアプリがポートを使っているため起動できないことを、ダイアログで知らせる。"""
    message = f"ポート {port} を他のアプリが使っているため、起動できません。そのアプリを終了してから、もう一度起動してください。"
    print(f"❌ {message}")
    try:
        if platform.system() == "Windows":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, "OmniShot", 0x10)
        elif platform.system() == "Darwin":
            script = f'display dialog "{message}" with title "OmniShot" buttons {{"OK"}} default button "OK" with icon stop'
            _run(["osascript", "-e", script], timeout=120)
    except Exception as e:
        print(f"⚠️ ダイアログを表示できませんでした: {e}")
