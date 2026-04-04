import sys
import os

# Dodaj katalog aplikacji do ścieżki Python
app_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, app_dir)

# Dodaj pakiety z user installation
sys.path.insert(0, '/home/MagicParty/.local/lib/python3.11/site-packages')

# Załaduj zmienne środowiskowe
from dotenv import load_dotenv
load_dotenv(os.path.join(app_dir, '.env'))

# Import aplikacji FastAPI
from app.main import app as application
