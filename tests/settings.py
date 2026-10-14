SECRET_KEY = 'tests-only'
DEBUG = False
USE_TZ = True
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'agent_content',
    'tests.testapp',
]
MIDDLEWARE = [
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
]
ROOT_URLCONF = 'tests.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'APP_DIRS': True, 'OPTIONS': {
    'context_processors': ['django.template.context_processors.request', 'django.contrib.auth.context_processors.auth',
                           'django.contrib.messages.context_processors.messages']}}]
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AGENT_CONTENT_REQUIRE_HTTPS = False
