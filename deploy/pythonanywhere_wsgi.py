"""Copy this content into PythonAnywhere's Web > WSGI configuration file.

The checkout is ~/togetherforbetter and private configuration is outside it.
Set the Web virtualenv to ~/togetherforbetter/.venv (Python 3.12).
"""
from pathlib import Path
import sys

project = Path.home() / 'togetherforbetter'
sys.path.insert(0, str(project))
from deploy.host_environment import activate
activate(Path.home() / 'together-private' / 'production.json')
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
