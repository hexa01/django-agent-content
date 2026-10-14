"""What agents may edit. Apps describe their models in `agent_resources.py`; the API is built from these descriptions.

    register(Resource(Post, lookup='slug', fields=['title', 'body'], create=True, defaults={'status': 'draft'}))
"""

from dataclasses import dataclass, field
from typing import Any, Callable

from django.utils.text import slugify


@dataclass
class Relation:
    """How agents refer to a related object (a ForeignKey or ManyToMany field): by `field` instead of its id.
    With create=True, unknown values are created; create_defaults(value) supplies the other fields (e.g. a slug)."""

    field: str = 'pk'
    create: bool = False
    create_defaults: Callable[[str], dict] | None = None


def slug_defaults(value):
    """create_defaults for models with a slug next to the name."""
    return {'slug': slugify(value)}


@dataclass
class Action:
    """Something done to one object, e.g. publishing: POST <resource>/<lookup>/<name>/ with params as JSON.
    fn(obj, data) does it and returns the object. description and params tell agents what it does and takes."""

    fn: Callable
    description: str = ''
    params: dict[str, str] = field(default_factory=dict)   # name -> what it is, e.g. {'published_at': 'ISO date, optional'}


@dataclass
class Inline:
    """Child rows edited as one list, e.g. an article's notes: GET or PUT <resource>/<lookup>/<name>/.
    PUT replaces the whole list (rows not sent are removed), in the order given."""

    model: Any
    fk: str
    fields: list[str]
    order_field: str | None = None


@dataclass
class Resource:
    model: Any
    fields: list[str]                                   # what agents may write (and read)
    name: str | None = None                             # URL name; default: the model's plural, e.g. "posts"
    singular: str | None = None                         # one item, for tool names; default: the model's name
    description: str = ''                               # what this content is, for agents
    lookup: str = 'pk'                                  # field used in item URLs
    read_only: list[str] = field(default_factory=list)  # extra fields agents may read but not write
    computed: dict[str, Callable] = field(default_factory=dict)  # read-only values, e.g. {'url': lambda o: ...}
    list_fields: list[str] | None = None                # fields in list results; default: lookup + first few
    relations: dict[str, Relation] = field(default_factory=dict)
    create: bool = False
    defaults: dict = field(default_factory=dict)        # forced on create, e.g. {'status': 'draft'}
    locked_fields: list[str] = field(default_factory=list)   # can't change while locked_if(obj) is true
    locked_if: Callable | None = None
    filters: list[str] = field(default_factory=list)    # fields allowed as ?field=value on lists
    search: Callable | None = None                      # search(queryset, text) for ?q=
    queryset: Callable | None = None                    # queryset() if not model.objects.all()
    singleton: Callable | None = None                   # get() for one-object resources (e.g. a site profile)
    actions: dict[str, Action | Callable] = field(default_factory=dict)   # POST <lookup>/<name>/
    inlines: dict[str, Inline] = field(default_factory=dict)

    def __post_init__(self):
        if self.name is None:
            self.name = slugify(str(self.model._meta.verbose_name_plural))
        if self.singular is None:
            self.singular = self.name if self.singleton else slugify(str(self.model._meta.verbose_name)).replace('-', '_')
        # a plain function is an action without params; its docstring's first line describes it
        self.actions = {name: action if isinstance(action, Action)
                        else Action(action, ((action.__doc__ or '').strip().splitlines() or [''])[0])
                        for name, action in self.actions.items()}
        if self.list_fields is None:
            self.list_fields = list(dict.fromkeys([self.lookup] + self.fields[:2] + self.read_only[:3]))

    @property
    def label(self):
        return f'{self.model._meta.app_label}.{self.model._meta.model_name}'

    def get_queryset(self):
        return self.queryset() if self.queryset else self.model._default_manager.all()

    def permissions(self):
        """The Django permissions a key's user needs to use this resource fully."""
        opts = self.model._meta
        perms = {f'{opts.app_label}.view_{opts.model_name}', f'{opts.app_label}.change_{opts.model_name}'}
        if self.create:
            perms.add(f'{opts.app_label}.add_{opts.model_name}')
        for name, relation in self.relations.items():
            related = self.model._meta.get_field(name).related_model._meta
            perms.add(f'{related.app_label}.view_{related.model_name}')
            if relation.create:
                perms.add(f'{related.app_label}.add_{related.model_name}')
        for inline in self.inlines.values():
            child = inline.model._meta
            perms |= {f'{child.app_label}.{action}_{child.model_name}' for action in ('view', 'add', 'change', 'delete')}
        return perms


_registry: dict[str, Resource] = {}


def register(resource: Resource) -> Resource:
    if resource.name in _registry:
        raise ValueError(f'An agent resource named "{resource.name}" is already registered.')
    _registry[resource.name] = resource
    return resource


def resources() -> dict[str, Resource]:
    return _registry
