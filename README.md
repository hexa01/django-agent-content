# django-agent-content

**Django + MCP: let AI agents edit your site's content, safely.**

Claude Code, Cursor and other MCP clients (through [agent-content-mcp](https://github.com/hexa01/agent-content-mcp)),
or any HTTP client, can read and edit the models you choose: blog posts, pages, profiles, products. You decide which
models and fields are editable. Agents use revocable API keys that act as a Django user, so permissions and the admin's
change history work as usual. New content can be forced to drafts, and nothing is ever deleted.

```
AI agent ──> MCP server ──HTTPS + API key──> your Django site: /api/agent/ ──> your models (via ModelForms)
```

## Install

```bash
pip install "django-agent-content @ https://github.com/hexa01/django-agent-content/archive/refs/tags/v0.1.1.tar.gz"
```

```python
# settings.py
INSTALLED_APPS = [..., 'agent_content']

# urls.py
path('api/agent/', include('agent_content.urls')),
```

```bash
python manage.py migrate
```

Requires Django 4.2+ and works with any database Django supports: it uses your project's `DATABASES`.

## Say what agents may edit

In each app whose content agents should edit, add `agent_resources.py` (like `admin.py`). Start from a scaffold:

```bash
python manage.py agent_content_scaffold blog     # writes blog/agent_resources.py, everything commented out
```

Then uncomment and adjust:

```python
from agent_content import Action, Relation, Resource, register, slug_defaults

from .models import Post

register(Resource(
    Post,
    lookup='slug',                                           # /api/agent/posts/<slug>/
    fields=['title', 'slug', 'excerpt', 'body', 'category', 'tags'],   # what agents may write
    read_only=['status', 'published_at'],                    # what they may only read
    relations={'category': Relation('name'),                 # refer to related objects by name, not id
               'tags': Relation('name', create=True, create_defaults=slug_defaults)},
    create=True, defaults={'status': 'draft'},               # new posts are always drafts
    locked_fields=['slug'], locked_if=lambda post: post.status == 'published',   # links never break
    filters=['status'],                                      # ?status=draft
    actions={'publish': Action(publish, 'Make the post public.',            # POST /api/agent/posts/<slug>/publish/
                               {'published_at': 'ISO date to show, optional'})},
))
```

Only listed fields are exposed. Saves go through a ModelForm and your model's `save()`, so validation and side
effects match the admin.

### Full example

[`tests/testapp`](https://github.com/hexa01/django-agent-content/tree/main/tests/testapp) is a small working app used by the tests:
[`models.py`](https://github.com/hexa01/django-agent-content/blob/main/tests/testapp/models.py) and its [`agent_resources.py`](https://github.com/hexa01/django-agent-content/blob/main/tests/testapp/agent_resources.py) show most
options together: references by name, tags created when missing, drafts by default, a slug that locks once
published, a filter, search, a `publish` action with a parameter, an inline list (an article's notes) and a
single-object resource (site settings).

### Resource options

| Option | Meaning |
|---|---|
| `fields` | Writable (and readable) fields. |
| `name` | URL name; default: the model's plural, e.g. `posts`. |
| `lookup` | Field used in item URLs; default `pk`. |
| `singular` | One item's name, used for tool names (`get_post`); default: the model's name. |
| `description` | What this content is, shown to agents. |
| `read_only` | Readable but not writable. |
| `computed` | Read-only values: `{'url': lambda obj: obj.get_absolute_url()}`. |
| `list_fields` | Fields shown in lists. |
| `relations` | `{'field': Relation('name', create=False)}` for ForeignKey/ManyToMany fields. |
| `create`, `defaults` | Allow creating; `defaults` are forced on create (e.g. a draft status). |
| `locked_fields`, `locked_if` | Fields that can't change while `locked_if(obj)` is true. |
| `filters`, `search` | `?field=value` filters; `search(queryset, text)` for `?q=`. |
| `queryset` | `queryset()` if not `Model.objects.all()`. |
| `singleton` | `get()` for one-object resources such as site settings: `/api/agent/<name>/`. |
| `actions` | `{'publish': Action(fn, 'what it does', {'param': 'what it is'})}`: `POST <lookup>/<name>/`; `fn(obj, data)` returns the object. A plain function also works (its docstring describes it). |
| `inlines` | `{'notes': Inline(Note, fk='article', fields=[...], order_field='position')}`: `GET`/`PUT <lookup>/notes/` replaces the list. |

## API keys

```bash
python manage.py agent_content_key --label "Claude Code, laptop"           # never expires
python manage.py agent_content_key --label "CI" --days 90
python manage.py agent_content_key --list
python manage.py agent_content_key --revoke ac_Ab12cd      # by prefix, or --revoke all --user agent-bot
```

The key is printed once; only its SHA-256 hash is stored. By default it acts as the user `agent-bot` (created if
missing, with no password and no admin access) and is granted exactly the permissions your registered resources need.
Keys can also be created, revoked and checked (last used, expiry) under **Admin › Agent content › API keys**.

Agents send `Authorization: Bearer <key>`.

## Endpoints

| Request | Does |
|---|---|
| `GET /api/agent/` | API version and a description of every resource the key may see: each field's kind, label, help text, limits, choices and whether it's required, plus actions with their params. [agent-content-mcp](https://github.com/hexa01/agent-content-mcp) builds its tools from this. |
| `GET <name>/` | List (`?field=value`, `?q=`). |
| `POST <name>/` | Create (when `create=True`). |
| `GET`, `PATCH <name>/<lookup>/` | Read, or change only the fields sent. |
| `POST <name>/<lookup>/<action>/` | Run an action. |
| `GET`, `PUT <name>/<lookup>/<inline>/` | Read or replace child rows. |

Errors are JSON: `{"error": "...", "fields": {"slug": ["..."]}}`, written so an agent can fix its request.

## Settings

All optional.

| Setting | Default | Meaning |
|---|---|---|
| `AGENT_CONTENT_MODULE` | `'agent_resources'` | File name looked up in each app. |
| `AGENT_CONTENT_ADMIN_BASE` | `'django.contrib.admin.ModelAdmin'` | Base class for the key admin, e.g. `'unfold.admin.ModelAdmin'` for Unfold. |
| `AGENT_CONTENT_RATE_LIMIT` | `120` | Requests per minute per key. |
| `AGENT_CONTENT_MAX_BODY` | `1000000` | Largest request body in bytes. |
| `AGENT_CONTENT_REQUIRE_HTTPS` | `None` | Refuse plain HTTP; `None` means "unless `DEBUG`". Behind a proxy, set Django's `SECURE_PROXY_SSL_HEADER`. |

Tip: add `Disallow: /api/` to your `robots.txt`.

## Security

- Keys are hashed, can expire, and can be revoked at any time; keys of inactive users stop working.
- What a key can do is its user's Django permissions. The API has no delete endpoints (inline lists replace their rows).
- HTTPS is required outside `DEBUG`; requests are rate-limited and size-limited.
- Every change is recorded in the admin's history under the key's user.

## Development

```bash
python -m venv .venv && .venv/bin/pip install "Django>=5.2"
.venv/bin/python runtests.py            # SQLite, no project needed
```

## Changelog

- **0.1.2**: package metadata for PyPI (summary, keywords, classifiers, links); README example app and wording.
- **0.1.1**: updates change only the fields sent (unsent text is left exactly as it was); actions take a
  description and params (`Action`); the API description adds field kinds, labels, `required`, `singular` and
  create defaults.
- **0.1.0**: first release.

## License

MIT
