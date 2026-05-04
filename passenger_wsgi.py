import sys
import os

# Dodaj katalog aplikacji do ścieżki Python
app_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, app_dir)

# Załaduj zmienne środowiskowe
from dotenv import load_dotenv
load_dotenv(os.path.join(app_dir, '.env'))

# Django WSGI application
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agent_krypto.settings')

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
