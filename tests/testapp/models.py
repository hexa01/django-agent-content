"""Small models standing in for a real site's content: articles with a category, tags, notes and a cover,
documents with a required file, plus a singleton."""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Category(models.Model):
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(unique=True)


class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(unique=True)


class Article(models.Model):
    title = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    summary = models.CharField(max_length=160, blank=True, help_text='One sentence for lists.')
    body = models.TextField()
    status = models.CharField(max_length=10, choices=[('draft', 'Draft'), ('published', 'Published')], default='draft')
    published_at = models.DateTimeField(null=True, blank=True)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL)
    tags = models.ManyToManyField(Tag, blank=True)
    cover = models.FileField(upload_to='covers/', blank=True, help_text='Shown above the article.')

    def save(self, *args, **kwargs):
        if self.status == 'published' and not self.published_at:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)


class Note(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='notes')
    text = models.CharField(max_length=200)
    position = models.PositiveSmallIntegerField(default=0)


def no_programs(file):
    if file.name.endswith('.exe'):
        raise ValidationError('Programs are not allowed.')


class Document(models.Model):
    """A model whose file is required, so it can only be created with an upload."""
    title = models.CharField(max_length=100)
    file = models.FileField(upload_to='documents/', validators=[no_programs])


class SiteInfo(models.Model):
    tagline = models.CharField(max_length=100, blank=True)
    owner = models.CharField(max_length=100, default='Owner')
    logo = models.FileField(upload_to='site/', blank=True)

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(pk=1)[0]
