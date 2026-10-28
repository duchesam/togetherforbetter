"""Small-pilot defaults. Use the host's native WSGI setup on PythonAnywhere."""
import os
bind = '0.0.0.0:' + os.getenv('PORT', '8000')
workers = 1
threads = 4
timeout = 60
# Do not put private paths, account recovery URLs or query strings into access logs.
accesslog = None
errorlog = '-'
capture_output = False
# Trust proxy headers only through Django's explicit deployment configuration.
forwarded_allow_ips = ''
