import json
from functools import wraps

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from . import conf
from .models import APIKey, KeyUsage


def error(status, message, **extra):
    return JsonResponse({'error': message, **extra}, status=status)


def _content_length(request):
    try:
        return int(request.META.get('CONTENT_LENGTH') or 0)
    except ValueError:
        return 0


def agent_view(view):
    """Every API request: HTTPS, an API key (not a session, so no CSRF), rate and size limits, JSON body.
    The view runs with request.user set to the key's user, request.data holding the parsed body and
    request.uploads the uploaded files (only for multipart POSTs: the JSON goes in a part named "data")."""

    @csrf_exempt
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if conf.get('AGENT_CONTENT_REQUIRE_HTTPS') and not request.is_secure():
            return error(403, 'HTTPS is required.')

        scheme, _, raw = request.headers.get('Authorization', '').partition(' ')
        key = APIKey.find(raw.strip()) if scheme.lower() == 'bearer' and raw else None
        if key is None:
            response = error(401, 'A valid API key is required: Authorization: Bearer <key>.')
            response['WWW-Authenticate'] = 'Bearer'
            return response

        if KeyUsage.hit(key) > conf.get('AGENT_CONTENT_RATE_LIMIT'):
            return error(429, 'Too many requests. Try again in a minute.')
        key.touch()

        request.data, request.uploads = {}, {}
        multipart = request.content_type == 'multipart/form-data'
        if multipart and request.method != 'POST':
            return error(400, 'File uploads use POST.')
        if multipart:
            # checked before Django reads the body, so an oversized upload is never stored
            limit = conf.get('AGENT_CONTENT_MAX_BODY') + conf.get('AGENT_CONTENT_MAX_UPLOAD')
            if _content_length(request) > limit:
                return error(413, f'The upload is too large. Files may be up to '
                                  f'{conf.get("AGENT_CONTENT_MAX_UPLOAD") // 1_000_000} MB.')
            raw = request.POST.get('data', '')
            request.uploads = request.FILES
        elif request.method in ('POST', 'PUT', 'PATCH'):
            if len(request.body) > conf.get('AGENT_CONTENT_MAX_BODY'):
                return error(413, 'The request body is too large.')
            raw = request.body
        if multipart or request.method in ('POST', 'PUT', 'PATCH'):
            try:
                request.data = json.loads(raw or b'{}')
            except ValueError:
                return error(400, 'The request body must be JSON (for uploads: the part named "data").')
            if not isinstance(request.data, dict):
                return error(400, 'The request body must be a JSON object.')

        request.user = key.user
        request.agent_key = key
        return view(request, *args, **kwargs)

    return wrapper
