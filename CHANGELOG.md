# Changelog

All notable changes to django-agent-content. Versions follow [semantic versioning](https://semver.org/).

## 0.2.0 (2026-10-30)

### Added
- File and image uploads. List a `FileField` or `ImageField` under a resource's `uploads`
  (`uploads=['cover']`, or `uploads={'cover': Upload(accept=['image/'], max_bytes=...)}`) and agents can set it:
  `POST <name>/<lookup>/<field>/` as multipart, or with the other fields in a multipart create. Uploads go through
  a ModelForm and `model.save()`, so the field's validators and the site's own processing run as in the admin.
- `AGENT_CONTENT_MAX_UPLOAD` setting (default 5 MB per file). An oversized upload is refused before it's read.
- The API description lists each resource's uploads with their kind, accepted types, size limit and whether a new
  item needs the file.

### Upgrading
- Nothing changes for existing resources. To let a key use newly registered uploads or resources, its user needs the
  matching permissions: create a key with `manage.py agent_content_key`, which grants them, or add them to the user
  in the admin.

## 0.1.2 (2026-10-15)

### Changed
- Package metadata for PyPI (summary, keywords, classifiers, links); README example app and wording.

## 0.1.1 (2026-10-14)

### Fixed
- Updates change only the fields sent; text that wasn't sent is left exactly as it was.

### Added
- Actions take a description and parameters (`Action`), shown to agents.
- The API description adds field kinds, labels, `required`, `singular` and create defaults.

## 0.1.0 (2026-10-14)

First release: API keys (hashed, expiring, revocable), a JSON API built from `agent_resources.py` registrations,
admin history for every change and no deletes.
