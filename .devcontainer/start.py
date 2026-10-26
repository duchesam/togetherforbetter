"""Start retained, private development services without duplicate processes."""
import os
import argparse
from pathlib import Path
import signal
import subprocess
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = Path(os.environ['PILOT_RUNTIME_DIR'])
PYTHON = ROOT / '.venv/bin/python'
MANAGE = str(ROOT / 'manage.py')
PORT = int(os.environ.get('PILOT_PORT', '8000'))
parser = argparse.ArgumentParser()
parser.add_argument('--restart', action='store_true')
options = parser.parse_args()


def running(pid_file, expected):
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
        arguments = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        return MANAGE.encode() in arguments and expected.encode() in arguments
    except (ValueError, OSError):
        return False


def start(name, arguments, expected):
    pid_file = RUNTIME / f'{name}.pid'
    if running(pid_file, expected):
        return
    with (RUNTIME / f'{name}.log').open('ab') as output:
        process = subprocess.Popen([str(PYTHON), MANAGE, *arguments], cwd=ROOT,
                                   stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                                   start_new_session=True)
    pid_file.write_text(str(process.pid))
    time.sleep(0.2)
    if process.poll() is not None:
        raise RuntimeError(f'{name} did not start; inspect its private runtime log locally.')


def stop(name, expected):
    pid_file = RUNTIME / f'{name}.pid'
    if running(pid_file, expected):
        os.kill(int(pid_file.read_text().strip()), signal.SIGTERM)
        for attempt in range(50):
            if not running(pid_file, expected):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError(f'{name} did not stop; inspect its private runtime log locally.')
    pid_file.unlink(missing_ok=True)


if options.restart:
    stop(f'web-{PORT}', 'runserver')
    stop('account-worker', 'deliver_emails')
start(f'web-{PORT}', ['runserver', f'0.0.0.0:{PORT}', '--noreload'], 'runserver')
start('account-worker', ['deliver_emails', '--watch', '--interval', '5'], 'deliver_emails')
for attempt in range(50):
    try:
        with urlopen(f'http://127.0.0.1:{PORT}/', timeout=2) as response:
            if response.status == 200 and b'Together for Better' in response.read():
                break
    except OSError:
        time.sleep(0.2)
else:
    raise RuntimeError('The pilot did not pass its HTTP readiness check.')
print('Pilot and local account worker are running. Open port 8000 from the Codespaces Ports panel.')
