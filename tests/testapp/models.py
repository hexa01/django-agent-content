"""Small models standing in for a real site's content: articles with a category, tags and notes, plus a singleton."""

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

    def save(self, *args, **kwargs):
        if self.status == 'published' and not self.published_at:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)


class Note(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='notes')
    text = models.CharField(max_length=200)
    position = models.PositiveSmallIntegerField(default=0)


class SiteInfo(models.Model):
    tagline = models.CharField(max_length=100, blank=True)
    owner = models.CharField(max_length=100, default='Owner')

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(pk=1)[0]
