import platform
import subprocess
import threading
import time
import webbrowser

from omnishot import create_app, paths
from omnishot.logs import add_log

if __name__ == '__main__':
    try:
        if platform.system() == "Windows":
            subprocess.run('cmd /c "for /f \"tokens=5\" %a in (\'netstat -aon ^| findstr 5001\') do taskkill /f /pid %a"', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=paths.CREATE_NO_WINDOW)
        else:
            subprocess.run("kill -9 $(lsof -t -i:5001)", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.3)
    except Exception: pass

    threading.Timer(0.5, lambda: webbrowser.open('http://127.0.0.1:5001')).start()
    add_log("🚀 OmniShot を起動中...")
    app = create_app()
    app.run(host='127.0.0.1', port=5001, debug=False, use_reloader=False, threaded=True)
