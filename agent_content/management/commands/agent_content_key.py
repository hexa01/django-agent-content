from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from agent_content.models import APIKey
from agent_content.registry import resources


class Command(BaseCommand):
    help = ('Create an API key (printed once), or list/revoke keys. The user is created if missing, as a non-staff '
            'account (it can\'t log into admin) with exactly the permissions the registered resources need.')

    def add_arguments(self, parser):
        parser.add_argument('--user', default='agent-bot', help='Username the key acts as (default: agent-bot).')
        parser.add_argument('--label', default='Agent', help='Where the key is used, e.g. "Claude Code, laptop".')
        expiry = parser.add_mutually_exclusive_group()
        expiry.add_argument('--days', type=int, help='Expire after this many days.')
        expiry.add_argument('--never', action='store_true', help='Never expire (the default).')
        parser.add_argument('--no-grant', action='store_true', help='Don\'t change the user\'s permissions.')
        parser.add_argument('--list', action='store_true', help='List keys instead of creating one.')
        parser.add_argument('--revoke', metavar='PREFIX', help='Revoke the key starting with PREFIX, or "all" for the user\'s keys.')

    def handle(self, *args, **options):
        User = get_user_model()
        if options['list']:
            for key in APIKey.objects.select_related('user'):
                self.stdout.write(f'{key.prefix}…  {key.status:8} {key.user}  {key.label}  '
                                  f'expires {key.expires_at or "never"}  last used {key.last_used_at or "never"}')
            return

        if options['revoke']:
            keys = APIKey.objects.filter(revoked_at__isnull=True)
            keys = keys.filter(user__username=options['user']) if options['revoke'] == 'all' else keys.filter(prefix__startswith=options['revoke'])
            count = keys.update(revoked_at=timezone.now())
            self.stdout.write(self.style.SUCCESS(f'Revoked {count} key(s).'))
            return

        user, created = User.objects.get_or_create(
            username=options['user'], defaults={'is_staff': False, 'is_active': True})
        if created:
            user.set_unusable_password()
            user.save()
        if not options['no_grant']:
            self.grant(user)

        expires = timezone.now() + timedelta(days=options['days']) if options['days'] else None
        key, raw = APIKey.generate(user, options['label'], expires)
        self.stdout.write(self.style.SUCCESS(f'Key for {user} ({"expires " + str(expires.date()) if expires else "never expires"}):'))
        self.stdout.write(raw)
        self.stdout.write('Copy it now: it is not stored and won\'t be shown again.')

    def grant(self, user):
        needed = set().union(*(r.permissions() for r in resources().values())) if resources() else set()
        if not needed:
            raise CommandError('No agent resources are registered (no agent_resources.py found).')
        for perm in sorted(needed):
            app_label, codename = perm.split('.')
            try:
                user.user_permissions.add(Permission.objects.get(content_type__app_label=app_label, codename=codename))
            except Permission.DoesNotExist:
                raise CommandError(f'Permission {perm} does not exist. Run migrate first.')
        self.stdout.write(f'{user} can: {", ".join(sorted(needed))}')
