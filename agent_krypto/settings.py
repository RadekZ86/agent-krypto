from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure-agent-krypto-change-me-in-production')

DEBUG = os.getenv('DEBUG', 'False').lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = [h.strip() for h in os.getenv('ALLOWED_HOSTS', '*').split(',') if h.strip()]

INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.staticfiles',
    'corsheaders',
    'app',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'app.middleware.SecurityHeadersMiddleware',
]

ROOT_URLCONF = 'agent_krypto.urls'

WSGI_APPLICATION = 'agent_krypto.wsgi.application'
ASGI_APPLICATION = 'agent_krypto.asgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'agent_krypto.db',
        'OPTIONS': {
            'timeout': 30,
            'init_command': "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA foreign_keys=ON;",
        },
    }
}

# Templates
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'app' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
            ],
        },
    },
]

# Static files
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'app' / 'static']
STATIC_ROOT = BASE_DIR / 'public' / 'static'

# CORS
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        'ALLOWED_ORIGINS',
        'https://agentkrypto.apka.org.pl,https://magicparty.usermd.net'
    ).split(',')
    if origin.strip()
]
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_METHODS = ['GET', 'POST', 'DELETE']
CORS_ALLOW_HEADERS = ['Content-Type']
CORS_PREFLIGHT_MAX_AGE = 600

# Timezone — project uses naive UTC datetimes
USE_TZ = False
TIME_ZONE = 'UTC'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --------------------------------------------------------------------------
# Logging — clear any pre-existing root handlers (Passenger may re-import
# the WSGI app, otherwise StreamHandlers stack and every log line repeats).
# Also silence DisallowedHost noise from bot scans (www.*, dev.*, en.* ...).
# --------------------------------------------------------------------------
import logging as _logging
for _h in list(_logging.getLogger().handlers):
    _logging.getLogger().removeHandler(_h)


class _DropDisallowedHost(_logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        return 'DisallowedHost' not in msg and 'Invalid HTTP_HOST header' not in msg


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'drop_disallowed_host': {
            '()': _DropDisallowedHost,
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'filters': ['drop_disallowed_host'],
        },
    },
    'loggers': {
        'django.security.DisallowedHost': {
            'handlers': [],
            'propagate': False,
            'level': 'CRITICAL',
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
            'filters': ['drop_disallowed_host'],
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}
