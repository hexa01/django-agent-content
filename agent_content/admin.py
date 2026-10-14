from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html
from django.utils.module_loading import import_string

from . import conf
from .models import APIKey

# a site using an admin theme (e.g. Unfold) sets AGENT_CONTENT_ADMIN_BASE to the theme's ModelAdmin
BaseAdmin = import_string(conf.get('AGENT_CONTENT_ADMIN_BASE'))


@admin.register(APIKey)
class APIKeyAdmin(BaseAdmin):
    list_display = ['label', 'user', 'key_start', 'state', 'expires_at', 'last_used_at', 'created_at']
    list_filter = ['user']
    search_fields = ['label', 'prefix', 'user__username']
    actions = ['revoke_keys']
    fields = ['user', 'label', 'expires_at']

    def get_readonly_fields(self, request, obj=None):
        # once created, only the label and expiry can change; the key itself never does
        return ['user', 'key_start', 'state', 'created_at', 'last_used_at', 'revoked_at'] if obj else []

    def get_fields(self, request, obj=None):
        return self.fields + (['key_start', 'state', 'created_at', 'last_used_at', 'revoked_at'] if obj else [])

    @admin.display(description='Key')
    def key_start(self, key):
        return f'{key.prefix}…'

    @admin.display(description='Status')
    def state(self, key):
        return key.status

    def save_model(self, request, obj, form, change):
        if change:
            return super().save_model(request, obj, form, change)
        raw = obj.assign_new_key()
        super().save_model(request, obj, form, change)
        self.message_user(request, format_html(
            'New key for {}: <code style="user-select:all">{}</code> Copy it now: it won\'t be shown again.', obj.user, raw,
        ), messages.WARNING)

    def has_delete_permission(self, request, obj=None):
        return False  # revoke instead, so the history of which key did what stays readable

    @admin.action(description='Revoke selected keys')
    def revoke_keys(self, request, queryset):
        count = queryset.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
        self.message_user(request, f'Revoked {count} key(s).')
