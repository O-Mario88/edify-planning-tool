"""A field's display label, read from a choice table built once per field.

Django's ``get_FOO_display()`` rebuilds the field's whole choice table on every
call (``dict(make_hashable(field.flatchoices))``). A field with a long list of
choices, read on every row of a country's plan, spent seconds rebuilding the
same table (2026-10-26: My Plan's export made 63,000 such calls). Choices are
fixed when the models load, so the table is built once and kept. The labels
stay lazy until read, so each request still reads its own language.
"""

from __future__ import annotations

from functools import cache

from django.utils.encoding import force_str
from django.utils.hashable import make_hashable


@cache
def _choices(model: type, field_name: str) -> dict:
    return dict(make_hashable(model._meta.get_field(field_name).flatchoices))


def label_for(model: type, field_name: str, value) -> str:
    """What ``get_<field_name>_display()`` answers for ``value`` on ``model``."""
    labels = _choices(model._meta.concrete_model, field_name)
    return force_str(labels.get(make_hashable(value), value), strings_only=True)


def choice_label(obj, field_name: str) -> str:
    """What ``obj.get_<field_name>_display()`` answers, without rebuilding
    the choice table."""
    value = getattr(obj, obj._meta.get_field(field_name).attname)
    return label_for(type(obj), field_name, value)
