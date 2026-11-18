"""Start Flask/Gunicorn and a supervised durable upload worker together."""
from __future__ import annotations

import logging
import signal
import subprocess
import sys
import time

logging.basicConfig(level=logging.INFO)
log = logging.getLogger('chimney-process-manager')


def main():
    gunicorn_cmd = [sys.executable, '-m', 'gunicorn', '--workers', '3',
                    '--timeout', '120', '--bind', '0.0.0.0:8000', 'app:app']
    web = subprocess.Popen(gunicorn_cmd)
    worker = subprocess.Popen([sys.executable, '-u', 'chimney_upload_worker.py'])
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
        for child in (worker, web):
            if child.poll() is None:
                child.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopping:
            code = web.poll()
            if code is not None:
                log.error('Web server exited with status %s', code)
                return code or 1
            if worker.poll() is not None:
                log.warning('Background upload worker exited; restarting in 5 seconds')
                time.sleep(5)
                if not stopping:
                    worker = subprocess.Popen([sys.executable, '-u', 'chimney_upload_worker.py'])
            time.sleep(1)
    finally:
        for child in (worker, web):
            if child.poll() is None:
                child.terminate()
        for child in (worker, web):
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
    return 0


if __name__ == '__main__':
    sys.exit(main())
