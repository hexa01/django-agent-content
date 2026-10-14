from django.apps import AppConfig
from django.utils.module_loading import autodiscover_modules


class AgentContentConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'agent_content'
    verbose_name = 'Agent content'

    def ready(self):
        # load every app's agent_resources.py (or the AGENT_CONTENT_MODULE name), like admin.py is loaded
        from . import conf
        autodiscover_modules(conf.get('AGENT_CONTENT_MODULE'))
