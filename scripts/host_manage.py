"""Run a Django command with the same private configuration used by WSGI."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy.host_environment import activate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, help='Absolute path to private production.json')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    if not arguments.command:
        parser.error('Supply a Django management command')
    try:
        activate(arguments.config)
    except (OSError, ValueError, RuntimeError):
        parser.exit(1, 'Cannot load private host configuration. Check the path, permissions and required settings.\n')
    from django.core.management import execute_from_command_line
    execute_from_command_line(['manage.py', *arguments.command])


if __name__ == '__main__':
    main()
