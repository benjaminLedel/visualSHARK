"""
Django settings for sntest project.

Generated by 'django-admin startproject' using Django 1.11.6.

For more information on this file, see
https://docs.djangoproject.com/en/1.11/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/1.11/ref/settings/
"""

import os
import sys

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TESTING = len(sys.argv) > 1 and sys.argv[1] == 'test'

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/1.11/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = None

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = []


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'corsheaders',
    'crispy_forms',
    'rest_framework',
    'rest_framework.authtoken',
    'rest_framework_mongoengine',
    'visualSHARK'
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'sntest.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'sntest.wsgi.application'


# Password validation
# https://docs.djangoproject.com/en/1.11/ref/settings/#auth-password-validators

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


# Internationalization
# https://docs.djangoproject.com/en/1.11/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/1.11/howto/static-files/
STATIC_ROOT = os.path.normpath(BASE_DIR + '/static/')
STATIC_URL = '/static/'

CORS_ORIGIN_WHITELIST = (
    '127.0.0.1',
    'localhost:8080',
)

CORS_ALLOW_HEADERS = (
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
    # need these for custom auth
    'x-user',
    'x-pass'
)

REST_FRAMEWORK = {
    'DEFAULT_FILTER_BACKENDS': ('rest_framework.filters.SearchFilter', 'rest_framework.filters.OrderingFilter'),
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework.authentication.TokenAuthentication',
        # 'rest_framework.authentication.BasicAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'visualSHARK.permissions.CustomPermission',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.LimitOffsetPagination',
    'PAGE_SIZE': 100,
    'STRICT_JSON': False
}

VERSION = '0.1.2'

COMPUTED_FILES = 'computed_files/'


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '%(levelname)s %(asctime)s %(name)s %(message)s'
        },
        'simple': {
            'format': '%(levelname)s %(message)s'
        },
    },
    'handlers': {
        'file_debug': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'formatter': 'verbose',
            'filename': os.path.normpath(BASE_DIR + '/logs/debug.log'),
            'maxBytes': 1024 * 1024 * 8,
            'backupCount': 3
        },
        'file_info': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'formatter': 'verbose',
            'filename': os.path.normpath(BASE_DIR + '/logs/info.log'),
            'maxBytes': 1024 * 1024 * 8,
            'backupCount': 3
        },
        'file_error': {
            'level': 'ERROR',
            'class': 'logging.handlers.RotatingFileHandler',
            'formatter': 'verbose',
            'filename': os.path.normpath(BASE_DIR + '/logs/error.log'),
            'maxBytes': 1024 * 1024 * 8,
            'backupCount': 3
        }
    },
    'loggers': {
        'django.request': {
            'handlers': ['file_error'],
            'level': 'ERROR',
            'propagate': True,
        },
        'root': {
            'handlers': ['file_debug', 'file_info', 'file_error'],
            'level': 'DEBUG',
            'propagate': True,
        },
    }
}

SUBSTITUTIONS = {
    'db_user': {'name': '$db_user', 'description': 'database username'},
    'db_password': {'name': '$db_password', 'description': 'database password'},
    'db_database': {'name': '$db_database', 'description': 'database name'},
    'db_hostname': {'name': '$db_hostname', 'description': 'hostname on which the database runs on'},
    'db_port': {'name': '$db_port', 'description': 'port on which the database listens'},
    'db_authentication': {'name': '$db_authentication', 'description': 'database used for authentication'},
    'path': {'name': '$path', 'description': 'path to the repository / the revision'},
    'plugin_path': {'name': '$plugin_path', 'description': 'path to the plugins root folder'},
    'project_name': {'name': '$project_name', 'description': 'Name of the project'},
    'revision': {'name': '$revision', 'description': 'revision hash of the revision which is processed'},
}

# this sets up mongomock connection to the database
TEST_RUNNER = 'sntest.test_runner.MockDbTestRunner'
