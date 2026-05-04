import os
from .base import *  # noqa: F401, F403

DEBUG = False
SECRET_KEY = os.environ.get('SECRET_KEY')

ALLOWED_HOSTS = [
    '.wattlelink.com.au',
    'wattlelink.com.au',
]
CSRF_TRUSTED_ORIGINS = [
    'https://*.wattlelink.com.au',
    'https://wattlelink.com.au',
]

# Static files
MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')  # noqa: F405
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')  # noqa: F405
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Security
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Celery
CELERY_BROKER_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

# Anthropic
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}
