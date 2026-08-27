from __future__ import annotations

from functools import lru_cache

from .orderedset import OrderedSet
from .template import URITemplate

__all__ = ("OrderedSet", "URITemplate", "expand", "partial", "variables")


@lru_cache(maxsize=256)
def _template(uri: str) -> URITemplate:
    return URITemplate(uri)


def expand(uri: str, var_dict=None, **kwargs) -> str:
    return _template(uri).expand(var_dict, **kwargs)


def partial(uri: str, var_dict=None, **kwargs) -> URITemplate:
    return _template(uri).partial(var_dict, **kwargs)


def variables(uri: str) -> OrderedSet:
    return OrderedSet(_template(uri).variable_names)
