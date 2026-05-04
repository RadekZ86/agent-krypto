"""WSGI config for Agent Krypto project."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agent_krypto.settings')

application = get_wsgi_application()
