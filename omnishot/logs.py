# 仕様: docs/spec/bugs/LOCAL-047_Windowsで絵文字を含むログの出力で起動直後にアプリが落ちる.md
import collections
import sys
import threading
import time

log_queue = collections.deque(maxlen=100)
log_condition = threading.Condition()
log_counter = 0


def safe_print(message):
    """コンソールの文字コードで表せない文字（絵文字など）があっても、例外を投げずに出力する。"""
    stream = sys.stdout
    if stream is None:
        return
    try:
        print(message, file=stream)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "ascii"
        print(message.encode(encoding, errors="replace").decode(encoding), file=stream)
    except Exception:
        pass


def add_log(message):
    global log_counter
    timestamp = time.strftime("%H:%M:%S")
    full_msg = f"[{timestamp}] {message}"
    safe_print(full_msg)
    with log_condition:
        log_counter += 1
        log_queue.append((log_counter, full_msg))
        log_condition.notify_all()
