import collections
import threading
import time

log_queue = collections.deque(maxlen=100)
log_condition = threading.Condition()
log_counter = 0


def add_log(message):
    global log_counter
    timestamp = time.strftime("%H:%M:%S")
    full_msg = f"[{timestamp}] {message}"
    print(full_msg)
    with log_condition:
        log_counter += 1
        log_queue.append((log_counter, full_msg))
        log_condition.notify_all()
