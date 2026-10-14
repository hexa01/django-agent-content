import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.db.models import F
from django.utils import timezone

PREFIX = 'ac_'


def _hash(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


class APIKey(models.Model):
    """A key an agent sends as `Authorization: Bearer <key>`. Only its hash is stored; the key is shown once."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='agent_keys',
        help_text='The key acts as this user, with its permissions. Use a dedicated user, e.g. "agent-bot".',
    )
    label = models.CharField(max_length=100, help_text='Where it is used, e.g. "Claude Code on my laptop".')
    prefix = models.CharField(max_length=12, editable=False, help_text='The start of the key, to recognise it.')
    key_hash = models.CharField(max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True, help_text='Empty means it never expires.')
    last_used_at = models.DateTimeField(null=True, blank=True, editable=False)
    revoked_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        verbose_name = 'API key'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.label} ({self.prefix}…)'

    def assign_new_key(self):
        """Give this (unsaved) key its secret. Returns the raw key: it exists only here, so show it to the person now."""
        raw = PREFIX + secrets.token_urlsafe(32)
        self.prefix, self.key_hash = raw[:10], _hash(raw)
        return raw

    @classmethod
    def generate(cls, user, label, expires_at=None):
        key = cls(user=user, label=label, expires_at=expires_at)
        raw = key.assign_new_key()
        key.save()
        return key, raw

    @classmethod
    def find(cls, raw):
        """The usable key for a raw value, or None (unknown, revoked, expired, or its user is inactive)."""
        key = cls.objects.select_related('user').filter(key_hash=_hash(raw)).first()
        return key if key and key.is_usable else None

    @property
    def is_usable(self):
        expired = self.expires_at is not None and self.expires_at <= timezone.now()
        return self.revoked_at is None and not expired and self.user.is_active

    @property
    def status(self):
        if self.revoked_at:
            return 'revoked'
        if self.expires_at and self.expires_at <= timezone.now():
            return 'expired'
        return 'active'

    def revoke(self):
        if not self.revoked_at:
            self.revoked_at = timezone.now()
            self.save(update_fields=['revoked_at'])

    def touch(self):
        """Record use, at most once a minute, so busy agents don't write on every request."""
        now = timezone.now()
        if not self.last_used_at or (now - self.last_used_at).total_seconds() > 60:
            APIKey.objects.filter(pk=self.pk).update(last_used_at=now)


class KeyUsage(models.Model):
    """Requests per key per minute, for the rate limit. Old rows are removed as new minutes start."""

    key = models.ForeignKey(APIKey, on_delete=models.CASCADE, related_name='+')
    minute = models.DateTimeField()
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['key', 'minute'], name='agent_content_usage_once_per_minute')]

    @classmethod
    def hit(cls, key):
        """Count a request; returns how many this key made in the current minute."""
        minute = timezone.now().replace(second=0, microsecond=0)
        if not cls.objects.filter(key=key, minute=minute).update(count=F('count') + 1):
            _, created = cls.objects.get_or_create(key=key, minute=minute, defaults={'count': 1})
            if created:
                cls.objects.filter(minute__lt=minute).delete()
            else:
                cls.objects.filter(key=key, minute=minute).update(count=F('count') + 1)
        return cls.objects.get(key=key, minute=minute).count
