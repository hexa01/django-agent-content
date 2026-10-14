import json
from datetime import timedelta
from io import StringIO
from pathlib import Path

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from agent_content.models import APIKey
from tests.testapp.models import Article, Category, Note, Tag

API = '/api/agent/'


def make_key(username='bot', *args):
    """A key from the command, so the user gets exactly the permissions the resources need."""
    out = StringIO()
    call_command('agent_content_key', '--user', username, '--label', 'tests', *args, stdout=out)
    raw = next(line for line in out.getvalue().splitlines() if line.startswith('ac_'))
    return get_user_model().objects.get(username=username), raw


class APITestCase(TestCase):
    def setUp(self):
        self.user, self.raw = make_key()
        Category.objects.create(name='Guides', slug='guides')
        self.live = Article.objects.create(slug='live', title='Live', body='Some text.', status='published')

    def call(self, method, path, data=None, key=None, **extra):
        body = json.dumps(data) if data is not None else None
        response = getattr(self.client, method)(API + path, body, content_type='application/json',
                                                HTTP_AUTHORIZATION=f'Bearer {key or self.raw}', **extra)
        return response.status_code, response.json()


class KeyTests(APITestCase):
    def test_requests_need_a_usable_key(self):
        self.assertEqual(self.client.get(API).status_code, 401)
        self.assertEqual(self.call('get', '', key='ac_wrong')[0], 401)
        key = APIKey.objects.get()
        key.expires_at = timezone.now() - timedelta(minutes=1)
        key.save()
        self.assertEqual(self.call('get', '')[0], 401)
        key.expires_at = None
        key.save()
        self.assertEqual(self.call('get', '')[0], 200)
        key.revoke()
        self.assertEqual(self.call('get', '')[0], 401)

    def test_inactive_user_keys_stop_working(self):
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.call('get', '')[0], 401)

    def test_only_a_hash_is_stored_and_the_bot_has_no_admin_or_delete(self):
        key = APIKey.objects.get()
        self.assertNotIn(self.raw, (key.key_hash, key.prefix))
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.has_usable_password())
        self.assertFalse(self.user.has_perm('testapp.delete_article'))
        self.assertTrue(self.user.has_perm('testapp.add_tag'))  # tags are created by name

    @override_settings(AGENT_CONTENT_REQUIRE_HTTPS=True)
    def test_plain_http_is_refused_when_https_is_required(self):
        self.assertEqual(self.call('get', '')[0], 403)
        self.assertEqual(self.call('get', '', secure=True)[0], 200)

    @override_settings(AGENT_CONTENT_RATE_LIMIT=2)
    def test_rate_limit(self):
        self.assertEqual([self.call('get', '')[0] for _ in range(3)], [200, 200, 429])

    def test_bad_json_and_large_bodies(self):
        response = self.client.post(API + 'articles/', 'not json', content_type='application/json',
                                    HTTP_AUTHORIZATION=f'Bearer {self.raw}')
        self.assertEqual(response.status_code, 400)
        with override_settings(AGENT_CONTENT_MAX_BODY=10):
            self.assertEqual(self.call('patch', 'site/', {'tagline': 'Longer than ten bytes.'})[0], 413)

    def test_command_expiry_list_and_revoke(self):
        make_key('other', '--days', '30')
        key = APIKey.objects.get(user__username='other')
        self.assertAlmostEqual((key.expires_at - timezone.now()).days, 29, delta=1)
        call_command('agent_content_key', '--user', 'other', '--revoke', 'all', stdout=StringIO())
        key.refresh_from_db()
        self.assertEqual(key.status, 'revoked')


class ReadTests(APITestCase):
    def test_index_describes_resources(self):
        status, body = self.call('get', '')
        self.assertEqual(body['version'], 1)
        articles = next(r for r in body['resources'] if r['name'] == 'articles')
        self.assertEqual(articles['fields']['summary']['help'], 'One sentence for lists.')
        self.assertTrue(articles['fields']['slug']['locked_when_published'])
        self.assertEqual(articles['fields']['tags']['refer_by'], 'name')
        self.assertEqual((articles['actions'], articles['inlines']), (['publish'], {'notes': ['text']}))

    def test_list_filter_search_and_read(self):
        Article.objects.create(slug='draft', title='A draft', body='x')
        self.assertEqual([a['slug'] for a in self.call('get', 'articles/?status=draft')[1]['results']], ['draft'])
        self.assertEqual([a['slug'] for a in self.call('get', 'articles/?q=live')[1]['results']], ['live'])
        status, article = self.call('get', 'articles/live/')
        self.assertEqual((status, article['words'], article['status']), (200, 2, 'published'))
        self.assertEqual(self.call('get', 'articles/nope/')[0], 404)
        self.assertEqual(self.call('get', 'widgets/')[0], 404)

    def test_permissions_come_from_the_user(self):
        self.user.user_permissions.clear()
        self.assertEqual(self.call('get', 'articles/')[0], 403)
        self.assertEqual(self.call('get', '')[1]['resources'], [])


class WriteTests(APITestCase):
    def test_create_is_always_a_draft_tags_by_name_and_logged(self):
        status, article = self.call('post', 'articles/', {
            'title': 'New', 'slug': 'new', 'body': 'Text.', 'category': 'Guides', 'tags': ['Django', 'New tag'],
        })
        self.assertEqual((status, article['status']), (201, 'draft'))
        self.assertEqual(sorted(article['tags']), ['Django', 'New tag'])
        self.assertEqual(Tag.objects.get(name='New tag').slug, 'new-tag')
        entry = LogEntry.objects.get(object_id=str(Article.objects.get(slug='new').pk))
        self.assertEqual(entry.user, self.user)
        self.assertTrue(entry.is_addition())

    def test_invalid_create_leaves_no_new_tags(self):
        status, body = self.call('post', 'articles/', {'title': 'No slug', 'body': 'x', 'tags': ['Orphan']})
        self.assertEqual(status, 400)
        self.assertIn('slug', body['fields'])
        self.assertFalse(Tag.objects.filter(name='Orphan').exists())

    def test_unwritable_and_invalid_fields_are_explained(self):
        status, body = self.call('patch', 'articles/live/', {'status': 'draft'})
        self.assertEqual(status, 400)
        self.assertIn("can't be written: status", body['error'])
        body = self.call('patch', 'articles/live/', {'category': 'Nope'})[1]
        self.assertIn('Existing: Guides', body['fields']['category'][0])
        self.assertIn('summary', self.call('patch', 'articles/live/', {'summary': 'x' * 200})[1]['fields'])

    def test_slug_locks_once_published(self):
        self.assertEqual(self.call('patch', 'articles/live/', {'slug': 'moved'})[0], 400)
        self.assertEqual(self.call('patch', 'articles/live/', {'slug': 'live'})[0], 200)  # unchanged is fine
        Article.objects.create(slug='draft', title='Draft', body='x')
        self.assertEqual(self.call('patch', 'articles/draft/', {'slug': 'renamed'})[0], 200)

    def test_partial_update_keeps_other_fields_and_logs_the_change(self):
        self.live.tags.add(Tag.objects.create(name='Django', slug='django'))
        self.assertEqual(self.call('patch', 'articles/live/', {'summary': 'Short.'})[0], 200)
        self.live.refresh_from_db()
        self.assertEqual((self.live.summary, self.live.title, self.live.status), ('Short.', 'Live', 'published'))
        self.assertEqual(list(self.live.tags.values_list('name', flat=True)), ['Django'])
        self.assertIn('Summary', LogEntry.objects.get(object_id=str(self.live.pk)).get_change_message())

    def test_action_runs_with_its_data(self):
        Article.objects.create(slug='draft', title='Draft', body='x')
        status, article = self.call('post', 'articles/draft/publish/', {'published_at': '2026-03-01T09:00:00+00:00'})
        self.assertEqual((status, article['status']), (200, 'published'))
        self.assertTrue(article['published_at'].startswith('2026-03-01'))
        self.assertEqual(self.call('post', 'articles/draft/publish/', {'published_at': 'soon'})[0], 400)
        self.assertEqual(self.call('get', 'articles/draft/publish/')[0], 405)

    def test_inline_is_replaced_in_order_and_unchanged_on_error(self):
        Note.objects.create(article=self.live, text='Old')
        status, body = self.call('put', 'articles/live/notes/', {'items': [{'text': 'First'}, {'text': 'Second'}]})
        self.assertEqual((status, [n['text'] for n in body['items']]), (200, ['First', 'Second']))
        self.assertEqual(self.call('put', 'articles/live/notes/', {'items': [{'text': ''}]})[0], 400)
        self.assertEqual(list(self.live.notes.order_by('position').values_list('text', flat=True)), ['First', 'Second'])

    def test_singleton_and_no_create_without_permission(self):
        status, body = self.call('patch', 'site/', {'tagline': 'Hello.'})
        self.assertEqual((status, body['tagline']), (200, 'Hello.'))
        self.assertEqual(self.call('patch', 'site/', {'owner': 'Someone'})[0], 400)


@override_settings(AGENT_CONTENT_MODULE='scaffold_test_output')
class ScaffoldTests(TestCase):
    def test_writes_a_commented_starter_and_never_overwrites(self):
        path = Path(__file__).parent / 'testapp' / 'scaffold_test_output.py'
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        call_command('agent_content_scaffold', 'testapp', stdout=StringIO())
        text = path.read_text()
        self.assertIn('#     Article,', text)
        self.assertNotIn('\nregister(', text)  # nothing is exposed until the developer uncomments it
        with self.assertRaises(CommandError):
            call_command('agent_content_scaffold', 'testapp', stdout=StringIO())
