import os
import dj_database_url
from .base import *  # noqa: F401, F403

DEBUG = False
SECRET_KEY = os.environ.get('SECRET_KEY')

ALLOWED_HOSTS = [
    '.run.app',
    '.wattlelink.com.au',
    'wattlelink.com.au',
]
CSRF_TRUSTED_ORIGINS = [
    'https://*.run.app',
    'https://*.wattlelink.com.au',
    'https://wattlelink.com.au',
]

# Database — Cloud SQL via Unix socket
if os.environ.get('CLOUD_SQL_CONNECTION'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME', 'wattlelink'),
            'USER': os.environ.get('DB_USER', 'wattlelink_user'),
            'PASSWORD': os.environ.get('DB_PASSWORD'),
            'HOST': '/cloudsql/' + os.environ.get('CLOUD_SQL_CONNECTION'),
        }
    }
elif os.environ.get('DATABASE_URL'):
    DATABASES = {
        'default': dj_database_url.config(conn_max_age=600)
    }

# Static files
MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')  # noqa: F405
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')  # noqa: F405
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Security
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# File storage — Google Cloud Storage
DEFAULT_FILE_STORAGE = 'storages.backends.gcloud.GoogleCloudStorage'
GS_BUCKET_NAME = os.environ.get('GCS_BUCKET', 'wattlelink-files')

# Celery
CELERY_BROKER_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

# Anthropic
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
