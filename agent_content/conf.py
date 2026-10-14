"""Settings, each optional. Override any of them in the project's settings.py."""

from django.conf import settings

DEFAULTS = {
    # the file each app uses to register what agents may edit
    'AGENT_CONTENT_MODULE': 'agent_resources',
    # admin base class for the API key admin, e.g. 'unfold.admin.ModelAdmin'
    'AGENT_CONTENT_ADMIN_BASE': 'django.contrib.admin.ModelAdmin',
    # requests per minute per key
    'AGENT_CONTENT_RATE_LIMIT': 120,
    # largest accepted request body, in bytes
    'AGENT_CONTENT_MAX_BODY': 1_000_000,
    # refuse plain http; None means "only when DEBUG is off"
    'AGENT_CONTENT_REQUIRE_HTTPS': None,
}


def get(name):
    value = getattr(settings, name, DEFAULTS[name])
    if name == 'AGENT_CONTENT_REQUIRE_HTTPS' and value is None:
        return not settings.DEBUG
    return value
