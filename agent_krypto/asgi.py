"""ASGI config for Agent Krypto project."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agent_krypto.settings')

application = get_asgi_application()
