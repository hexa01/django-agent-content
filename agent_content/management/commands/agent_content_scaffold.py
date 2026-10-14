from pathlib import Path

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import models

from agent_content import conf

HEADER = '''"""What AI agents may edit in this app, through agent_content's API.

Everything below starts commented out: uncomment the models and fields agents should be able to change.
Only listed fields are exposed. Docs: the Resource options in agent_content/registry.py.
"""

from agent_content import Inline, Relation, Resource, register, slug_defaults  # noqa: F401

'''


class Command(BaseCommand):
    help = 'Write a starter agent_resources.py for an app, listing its models and editable fields (all commented out).'

    def add_arguments(self, parser):
        parser.add_argument('app_label')

    def handle(self, app_label, **options):
        try:
            config = apps.get_app_config(app_label)
        except LookupError:
            raise CommandError(f'No installed app "{app_label}".')
        path = Path(config.path) / f'{conf.get("AGENT_CONTENT_MODULE")}.py'
        if path.exists():
            raise CommandError(f'{path} already exists; not overwriting it.')

        blocks = [self.block(model) for model in config.get_models()]
        imports = f'# from .models import {", ".join(m.__name__ for m in config.get_models())}\n\n' if blocks else ''
        path.write_text(HEADER + imports + '\n\n'.join(blocks) + '\n')
        self.stdout.write(self.style.SUCCESS(f'Wrote {path}. Review it, uncomment what agents may edit, then restart.'))

    def block(self, model):
        fields, relations = [], []
        for field in model._meta.get_fields():
            if not getattr(field, 'concrete', False) or field.auto_created or not field.editable:
                continue
            if isinstance(field, (models.FileField, models.AutoField)) or field.name in ('password', 'is_superuser', 'is_staff'):
                continue
            fields.append(field.name)
            if field.many_to_one or field.many_to_many:
                relations.append(field.name)
        lookup = 'slug' if any(f.name == 'slug' for f in model._meta.fields) else 'pk'
        lines = [
            f'# register(Resource(',
            f'#     {model.__name__},',
            f'#     lookup={lookup!r},',
            f'#     fields={fields!r},',
            f'#     # read_only=[],            # readable but not writable, e.g. status or dates',
            f'#     # create=False,            # True to allow new ones; set defaults={{...}} to force e.g. a draft status',
        ]
        if relations:
            rel = ', '.join(f'{name!r}: Relation("name")' for name in relations)
            lines.append(f'#     # relations={{{rel}}},  # refer to related objects by a field instead of id')
        lines.append('# ))')
        return '\n'.join(lines)
