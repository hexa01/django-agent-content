from django.core.exceptions import ValidationError
from django.utils.dateparse import parse_datetime

from agent_content import Action, Inline, Relation, Resource, register, slug_defaults

from .models import Article, Category, Note, SiteInfo  # noqa: F401


def publish(article, data):
    when = data.get('published_at')
    published_at = parse_datetime(when) if when else None
    if when and published_at is None:
        raise ValidationError('published_at must be an ISO date.')
    article.status = 'published'
    if published_at:
        article.published_at = published_at
    article.save()
    return article


register(Resource(
    Article,
    lookup='slug',
    fields=['title', 'slug', 'summary', 'body', 'category', 'tags'],
    read_only=['status', 'published_at'],
    computed={'words': lambda article: len(article.body.split())},
    list_fields=['slug', 'title', 'status'],
    relations={'category': Relation('name'), 'tags': Relation('name', create=True, create_defaults=slug_defaults)},
    create=True,
    defaults={'status': 'draft'},
    locked_fields=['slug'],
    locked_if=lambda article: article.status == 'published',
    filters=['status'],
    search=lambda articles, text: articles.filter(title__icontains=text),
    actions={'publish': Action(publish, 'Make the article public.', {'published_at': 'ISO date, optional.'})},
    inlines={'notes': Inline(Note, fk='article', fields=['text'], order_field='position')},
))

register(Resource(SiteInfo, name='site', singleton=SiteInfo.load, fields=['tagline'], read_only=['owner']))
