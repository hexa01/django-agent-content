"""Let AI agents edit a Django site's content through a small, permission-checked JSON API.

Apps say what may be edited in an `agent_resources.py` (see registry.py); keys are managed in admin
or with `manage.py agent_content_key`."""

from .registry import Action, Inline, Relation, Resource, register, slug_defaults

__all__ = ['Action', 'Inline', 'Relation', 'Resource', 'register', 'slug_defaults']
