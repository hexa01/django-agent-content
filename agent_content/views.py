"""The API, built from the registered resources (see registry.py). JSON in, JSON out; saves go through
ModelForms and model.save(), so validation and side effects match the admin. Nothing is ever deleted,
except child rows replaced through an inline."""

from django.contrib.admin.models import ADDITION, CHANGE, LogEntry
from django.contrib.admin.utils import construct_change_message
from django.core.exceptions import FieldDoesNotExist, ObjectDoesNotExist, ValidationError
from django.db import models, transaction
from django.forms import modelform_factory
from django.forms.models import model_to_dict
from django.http import JsonResponse

from .auth import agent_view, error
from .registry import resources

API_VERSION = 1
LIST_LIMIT = 100


class APIError(Exception):
    def __init__(self, status, message, **extra):
        super().__init__(message)
        self.response = error(status, message, **extra)


# reading

def _value(obj, name, resource):
    try:
        field = obj._meta.get_field(name)
    except FieldDoesNotExist:  # e.g. a property listed in read_only
        field = None
    relation = resource.relations.get(name)
    if field is not None and field.many_to_many:
        return [getattr(item, relation.field) if relation else item.pk for item in getattr(obj, name).all()]
    if field is not None and field.many_to_one:
        related = getattr(obj, name)
        if related is None:
            return None
        return getattr(related, relation.field) if relation else related.pk
    value = getattr(obj, name)
    if isinstance(value, models.fields.files.FieldFile):
        return value.url if value else None
    return value


def serialize(obj, resource, full=True):
    """All readable fields, computed values and inline lists; or with full=False, just the list fields."""
    if not full:
        return {name: _value(obj, name, resource) for name in resource.list_fields}
    names = dict.fromkeys([resource.lookup] + resource.fields + resource.read_only)
    data = {name: _value(obj, name, resource) for name in names}
    data.update({name: fn(obj) for name, fn in resource.computed.items()})
    data.update({name: _inline_rows(obj, inline) for name, inline in resource.inlines.items()})
    return data


def _inline_rows(obj, inline):
    rows = inline.model._default_manager.filter(**{inline.fk: obj})
    if inline.order_field:
        rows = rows.order_by(inline.order_field, 'pk')
    return [{name: getattr(row, name) for name in inline.fields} for row in rows]


def describe(resource):
    """What an agent needs to know to use a resource: fields with their help text, limits and choices."""
    fields = {}
    for name in dict.fromkeys(resource.fields + resource.read_only):
        try:
            field = resource.model._meta.get_field(name)
        except FieldDoesNotExist:
            continue
        info = {'type': field.get_internal_type(), 'writable': name in resource.fields}
        if getattr(field, 'help_text', ''):
            info['help'] = str(field.help_text)
        if getattr(field, 'max_length', None):
            info['max_length'] = field.max_length
        if field.choices:
            info['choices'] = [value for value, _ in field.choices]
        if name in resource.relations:
            info['refer_by'] = resource.relations[name].field
            info['creates_missing'] = resource.relations[name].create
        if name in resource.locked_fields:
            info['locked_when_published'] = True
        fields[name] = info
    return {
        'name': resource.name,
        'model': str(resource.model._meta.verbose_name),
        'lookup': None if resource.singleton else resource.lookup,
        'create': resource.create,
        'fields': fields,
        'computed': list(resource.computed),
        'filters': resource.filters,
        'search': resource.search is not None,
        'actions': list(resource.actions),
        'inlines': {name: inline.fields for name, inline in resource.inlines.items()},
    }


# writing

def _resolve_relations(resource, data):
    """Turn names (or other refer_by values) into ids, creating missing ones where the relation allows it."""
    out, errors = dict(data), {}
    for name, relation in resource.relations.items():
        if name not in data:
            continue
        field = resource.model._meta.get_field(name)
        manager = field.related_model._default_manager

        def find(value):
            obj = manager.filter(**{relation.field: value}).first()
            if obj is None and relation.create:
                extra = relation.create_defaults(value) if relation.create_defaults else {}
                obj = manager.create(**{relation.field: value, **extra})
            return obj

        values = data[name]
        if field.many_to_many:
            if not isinstance(values, list):
                errors[name] = ['Send a list.']
                continue
            found = [find(value) for value in values]
            missing = [value for value, obj in zip(values, found) if obj is None]
            if missing:
                errors[name] = [f'Not found: {", ".join(map(str, missing))}.']
            out[name] = [obj.pk for obj in found if obj]
        elif values in (None, ''):
            out[name] = None
        else:
            obj = find(values)
            if obj is None:
                choices = ', '.join(str(v) for v in manager.values_list(relation.field, flat=True)[:30])
                errors[name] = [f'No {field.related_model._meta.verbose_name} "{values}". Existing: {choices}.']
            else:
                out[name] = obj.pk
    return out, errors


def _current_values(instance, resource):
    values = model_to_dict(instance, fields=resource.fields)
    for name, value in values.items():
        if isinstance(value, list):  # many-to-many: model_to_dict gives objects; forms want ids
            values[name] = [getattr(item, 'pk', item) for item in value]
    return values


def save(request, resource, instance, data):
    """Validate and save a create (instance=None) or a partial update. Returns the saved object."""
    unknown = sorted(set(data) - set(resource.fields))
    if unknown:
        raise APIError(400, f'These fields can\'t be written: {", ".join(unknown)}. Writable: {", ".join(resource.fields)}.')

    if instance is not None and resource.locked_if and resource.locked_if(instance):
        current = _current_values(instance, resource)
        locked = [name for name in resource.locked_fields if name in data and data[name] != current.get(name)]
        if locked:
            raise APIError(400, f'{", ".join(locked)} can\'t change once published (links to it would break).')

    adding = instance is None
    with transaction.atomic():
        data, errors = _resolve_relations(resource, data)
        if errors:
            transaction.set_rollback(True)
            raise APIError(400, 'Some fields are invalid.', fields=errors)

        # a create validates every writable field; an update only the ones sent, so the rest stay untouched
        target = resource.model(**resource.defaults) if adding else instance
        fields = resource.fields if adding else [name for name in resource.fields if name in data]
        form = modelform_factory(resource.model, fields=fields)(data=data, instance=target)
        if not form.is_valid():
            transaction.set_rollback(True)
            raise APIError(400, 'Some fields are invalid.', fields={
                name: [item['message'] for item in items] for name, items in form.errors.get_json_data().items()})
        obj = form.save()
        log(request, obj, ADDITION if adding else CHANGE, construct_change_message(form, None, adding))
    return obj


def log(request, obj, flag, message):
    """Record the change in the admin's history for this object, under the key's user."""
    if hasattr(LogEntry.objects, 'log_actions'):  # Django 5.1+
        LogEntry.objects.log_actions(request.user.pk, [obj], flag, message, single_object=True)
    else:
        from django.contrib.contenttypes.models import ContentType
        LogEntry.objects.log_action(request.user.pk, ContentType.objects.get_for_model(obj).pk,
                                    obj.pk, str(obj), flag, message)


def replace_inline(request, resource, obj, name, inline):
    rows = request.data.get('items')
    if not isinstance(rows, list):
        raise APIError(400, f'Send {{"items": [...]}}, each with: {", ".join(inline.fields)}.')
    Form = modelform_factory(inline.model, fields=inline.fields)
    forms = [Form(data=row if isinstance(row, dict) else {}) for row in rows]
    errors = {f'items[{i}]': {k: [e['message'] for e in v] for k, v in form.errors.get_json_data().items()}
              for i, form in enumerate(forms) if not form.is_valid()}
    if errors:
        raise APIError(400, 'Some items are invalid.', fields=errors)
    with transaction.atomic():
        inline.model._default_manager.filter(**{inline.fk: obj}).delete()
        for position, form in enumerate(forms):
            row = form.save(commit=False)
            setattr(row, inline.fk, obj)
            if inline.order_field:
                setattr(row, inline.order_field, position)
            row.save()
        log(request, obj, CHANGE, [{'changed': {'fields': [name]}}])


# helpers

def _resource(name):
    resource = resources().get(name)
    if resource is None:
        raise APIError(404, f'No resource "{name}". Available: {", ".join(resources())}.')
    return resource


def _require(request, perm):
    if not request.user.has_perm(perm):
        raise APIError(403, f'This key\'s user lacks the permission "{perm}".')


def _perm(resource, action):
    return f'{resource.model._meta.app_label}.{action}_{resource.model._meta.model_name}'


def _object(resource, lookup=None):
    if resource.singleton:
        return resource.singleton()
    obj = resource.get_queryset().filter(**{resource.lookup: lookup}).first()
    if obj is None:
        raise APIError(404, f'No {resource.model._meta.verbose_name} with {resource.lookup} "{lookup}".')
    return obj


def handles_errors(view):
    def wrapper(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except APIError as exc:
            return exc.response
        except ValidationError as exc:
            return error(400, ' '.join(exc.messages))
        except ObjectDoesNotExist as exc:
            return error(404, str(exc))
    return wrapper


def _not_allowed(*methods):
    response = error(405, f'Use {" or ".join(methods)}.')
    response['Allow'] = ', '.join(methods)
    return response


# views

@agent_view
@handles_errors
def index(request):
    visible = [r for r in resources().values() if request.user.has_perm(_perm(r, 'view'))]
    return JsonResponse({'version': API_VERSION, 'resources': [describe(r) for r in visible]})


@agent_view
@handles_errors
def collection(request, name):
    resource = _resource(name)
    if resource.singleton:
        return _item(request, resource, None)
    if request.method == 'GET':
        _require(request, _perm(resource, 'view'))
        queryset = resource.get_queryset()
        for key in resource.filters:
            if key in request.GET:
                queryset = queryset.filter(**{key: request.GET[key]})
        if (text := request.GET.get('q', '').strip()) and resource.search:
            queryset = resource.search(queryset, text)
        items = list(queryset[:LIST_LIMIT])
        return JsonResponse({'results': [serialize(obj, resource, full=False) for obj in items]})
    if request.method == 'POST':
        if not resource.create:
            raise APIError(405, f'New {resource.name} can\'t be created through the API.')
        _require(request, _perm(resource, 'add'))
        obj = save(request, resource, None, request.data)
        return JsonResponse(serialize(obj, resource), status=201)
    return _not_allowed('GET', 'POST')


@agent_view
@handles_errors
def item(request, name, lookup):
    return _item(request, _resource(name), lookup)


def _item(request, resource, lookup):
    if request.method == 'GET':
        _require(request, _perm(resource, 'view'))
        return JsonResponse(serialize(_object(resource, lookup), resource))
    if request.method == 'PATCH':
        _require(request, _perm(resource, 'change'))
        obj = save(request, resource, _object(resource, lookup), request.data)
        return JsonResponse(serialize(obj, resource))
    return _not_allowed('GET', 'PATCH')


@agent_view
@handles_errors
def member(request, name, lookup, sub):
    """POST <lookup>/<action>/ runs an action; GET or PUT <lookup>/<inline>/ reads or replaces child rows."""
    resource = _resource(name)
    obj = _object(resource, lookup)
    if sub in resource.actions:
        if request.method != 'POST':
            return _not_allowed('POST')
        _require(request, _perm(resource, 'change'))
        with transaction.atomic():
            obj = resource.actions[sub](obj, request.data) or obj
            log(request, obj, CHANGE, [{'changed': {'fields': [sub]}}])
        return JsonResponse(serialize(obj, resource))
    if sub in resource.inlines:
        inline = resource.inlines[sub]
        if request.method == 'GET':
            _require(request, _perm(resource, 'view'))
            return JsonResponse({'items': _inline_rows(obj, inline)})
        if request.method == 'PUT':
            for action in ('add', 'change', 'delete'):
                _require(request, f'{inline.model._meta.app_label}.{action}_{inline.model._meta.model_name}')
            replace_inline(request, resource, obj, sub, inline)
            return JsonResponse({'items': _inline_rows(obj, inline)})
        return _not_allowed('GET', 'PUT')
    raise APIError(404, f'No action or list "{sub}" on {resource.name}. '
                        f'Actions: {", ".join(resource.actions) or "none"}. Lists: {", ".join(resource.inlines) or "none"}.')
