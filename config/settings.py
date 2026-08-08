import os
import dotenv
from pathlib import Path
from datetime import timedelta
from urllib.parse import urlsplit


from decimal import Decimal, ROUND_HALF_UP
from django.core.exceptions import ImproperlyConfigured


def _env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default

    return value.lower() in {'1', 'true', 'yes', 'on'}


def _default_s3_domain(bucket_name, region_name):
    if not bucket_name:
        return None

    if region_name:
        return f'{bucket_name}.s3.{region_name}.amazonaws.com'

    return f'{bucket_name}.s3.amazonaws.com'


def _normalize_origin(value):
    value = (value or '').strip()
    if not value:
        return None

    parsed = urlsplit(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        return None

    return f'{parsed.scheme}://{parsed.netloc}'


def _parse_origin_list(value):
    origins = []
    for raw_origin in (value or '').split(','):
        origin = _normalize_origin(raw_origin)
        if origin:
            origins.append(origin)

    return origins


def _unique_list(values):
    seen = set()
    items = []
    for value in values:
        if value in seen:
            continue

        seen.add(value)
        items.append(value)

    return items


def _build_trusted_origins(frontend_url, origins_env):
    return _unique_list(
        _parse_origin_list(origins_env) + _parse_origin_list(frontend_url)
    )

BASE_DIR = Path(__file__).resolve().parent.parent
dotenv_file = os.path.join(BASE_DIR, ".env")
if os.path.isfile(dotenv_file):
    dotenv.load_dotenv(dotenv_file)


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ['SECRET_KEY']


DEBUG = os.environ.get('DJANGO_DEBUG', 'False') == 'True'
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'development').lower()
USE_S3_STORAGE = _env_flag('USE_S3_STORAGE', default=ENVIRONMENT != 'development')
ALLOWED_HOSTS = [
    "localhost",
    "127.0.0.1",
    ".ngrok-free.app",
    ".railway.app",
]


AUTH_USER_MODEL = "accounts.User"

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'corsheaders',
    'rest_framework',
    'storages',
    'django_celery_beat',
    
    "apps.accounts.apps.AccountsConfig",
    "apps.analytics.apps.AnalyticsConfig",
    "apps.contacts.apps.ContactsConfig",
    "apps.content.apps.ContentConfig",
    "apps.campaign.apps.CampaignConfig",
    "apps.sms.apps.SmsConfig",
    "apps.shopify.apps.ShopifyConfig",
    "apps.payment.apps.PaymentConfig",
    "apps.automation.apps.AutomationConfig",
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# Backward-compatible env lookup while standardizing on FRONTEND_URL.
FRONTEND_URL = os.environ.get('FRONTEND_URL') or os.environ.get('FRONTEND_URL') or 'http://localhost:3000'

CREDIT_RATE = Decimal("100")

VONAGE_ID = os.environ.get('VONAGE_ID')
VONAGE_TOKEN = os.environ.get('VONAGE_TOKEN')

SHOPIFY_API_KEY = os.environ.get('SHOPIFY_API_KEY', '')
SHOPIFY_API_SECRET = os.environ.get('SHOPIFY_API_SECRET', '')
SHOPIFY_SCOPES = os.environ.get('SHOPIFY_SCOPES', 'read_customers,write_customers')
SHOPIFY_REDIRECT_URI = os.environ.get('SHOPIFY_REDIRECT_URI', '')
SHOPIFY_API_VERSION = os.environ.get('SHOPIFY_API_VERSION', '2025-01')
SHOPIFY_APP_URL = os.environ.get('SHOPIFY_APP_URL', '')

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')
OPENAI_API_BASE_URL = os.environ.get('OPENAI_API_BASE_URL', 'https://api.openai.com/v1')
OPENAI_TIMEOUT_SECONDS = int(os.environ.get('OPENAI_TIMEOUT_SECONDS', '30'))


ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "apps.accounts.authentication.ShopifyAuthentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DATABASE_NAME', 'railway'),
        'USER': os.environ.get('DATABASE_USER', 'postgres'),
        'PASSWORD': os.environ.get('DATABASE_PASSWORD', ''),
        'HOST': os.environ.get('DATABASE_HOST', 'localhost'),
        'PORT': os.environ.get('DATABASE_PORT', '5432'),
    }
}

# Celery Configuration
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes
CELERY_TIMEZONE = 'Europe/Copenhagen'
CELERY_ENABLE_UTC = False
CELERY_CACHE_BACKEND = 'default'
CELERY_IMPORTS = ("apps.sms.tasks", "apps.accounts.tasks")
CELERY_BROKER_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


CELERY_TIMEZONE = 'Europe/Copenhagen'
CELERY_TASK_TRACK_STARTED = True
# CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True
DEFAULT_FROM_EMAIL = 'support@sendperplane.com'
NEW_USER_NOTIFICATION_EMAIL = os.environ.get('NEW_USER_NOTIFICATION_EMAIL') or os.environ.get('EMAIL_HOST_USER', '')

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'


_origins_env = os.environ.get('ORIGINS', '')
CORS_ALLOWED_ORIGINS = _build_trusted_origins(FRONTEND_URL, _origins_env)
CSRF_TRUSTED_ORIGINS = list(CORS_ALLOWED_ORIGINS)

CORS_ALLOW_CREDENTIALS = True

CORS_ALLOW_HEADERS = ["accept",
                                              "accept-encoding",
                                              "authorization",
                                              "content-type",
                                              "dnt",
                                              "users",
                                              "origin",
                                              "user-agent",
                                              "x-csrftoken",
                                              "options",
                                              "x-requested-with",
                                              "shopify-domain"]

EMAIL_HOST = 'smtp.privateemail.com'
EMAIL_USE_TLS = True
EMAIL_PORT = 587
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD')

# Logging Configuration
# Explicit root/console handler so logger calls show up in Railway's log
# stream even with DEBUG=False (Django's default logging drops most of it).
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

# STATIC_ROOT = BASE_DIR / "staticfiles"
STATIC_URL = "/static/"
MEDIA_ROOT = BASE_DIR / 'media'
MEDIA_URL = '/media/'

if USE_S3_STORAGE:
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME', '')
    AWS_S3_REGION_NAME = (
        os.environ.get('AWS_S3_REGION_NAME')
        or os.environ.get('AWS_DEFAULT_REGION')
        or os.environ.get('AWS_REGION')
    )
    AWS_S3_CUSTOM_DOMAIN = (
        os.environ.get('AWS_S3_CUSTOM_DOMAIN')
        or os.environ.get('AWS_CLOUDFRONT_DOMAIN')
        or _default_s3_domain(AWS_STORAGE_BUCKET_NAME, AWS_S3_REGION_NAME)
    )
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = False
    AWS_S3_FILE_OVERWRITE = False
    AWS_S3_SIGNATURE_VERSION = 's3v4'

    if not AWS_STORAGE_BUCKET_NAME:
        raise ImproperlyConfigured(
            'AWS_STORAGE_BUCKET_NAME must be set when S3 storage is enabled.'
        )

    storage_options = {
        'access_key': AWS_ACCESS_KEY_ID,
        'secret_key': AWS_SECRET_ACCESS_KEY,
        'bucket_name': AWS_STORAGE_BUCKET_NAME,
        'region_name': AWS_S3_REGION_NAME,
        'default_acl': AWS_DEFAULT_ACL,
        'querystring_auth': AWS_QUERYSTRING_AUTH,
        'file_overwrite': AWS_S3_FILE_OVERWRITE,
        'signature_version': AWS_S3_SIGNATURE_VERSION,
    }
    if AWS_S3_CUSTOM_DOMAIN:
        storage_options['custom_domain'] = AWS_S3_CUSTOM_DOMAIN

    STORAGES = {
        'default': {
            'BACKEND': 'storages.backends.s3.S3Storage',
            'OPTIONS': storage_options,
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    }

    if AWS_S3_CUSTOM_DOMAIN:
        MEDIA_URL = f'https://{AWS_S3_CUSTOM_DOMAIN.rstrip("/")}/'
else:
    STORAGES = {
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    }
