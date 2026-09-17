import os
import platform
import subprocess
import sys

CREATE_NO_WINDOW = 0x08000000 if platform.system() == "Windows" else 0


def get_startupinfo():
    if platform.system() == "Windows":
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0  # SW_HIDE
            return si
        except Exception:
            return None
    return None


if getattr(sys, 'frozen', False):
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    EXE_DIR = os.path.dirname(sys.executable)
    if "MacOS" in EXE_DIR:
        EXE_DIR = os.path.abspath(os.path.join(EXE_DIR, "../../../"))
else:
    # __file__ is omnishot/paths.py, so go up two levels to reach the repo root
    # (one level was enough when this logic lived directly in the root app.py).
    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    EXE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TEMPLATE_FOLDER = os.path.join(base_path, 'templates')
STATIC_FOLDER = os.path.join(base_path, 'static')

SAVE_DIR = os.path.join(EXE_DIR, "captures")
os.makedirs(SAVE_DIR, exist_ok=True)
