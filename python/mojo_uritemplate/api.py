from __future__ import annotations

from .orderedset import OrderedSet
from .template import URITemplate

__all__ = ("OrderedSet", "URITemplate", "expand", "partial", "variables")


def expand(uri: str, var_dict=None, **kwargs) -> str:
    return URITemplate(uri).expand(var_dict, **kwargs)


def partial(uri: str, var_dict=None, **kwargs) -> URITemplate:
    return URITemplate(uri).partial(var_dict, **kwargs)


def variables(uri: str) -> OrderedSet:
    return OrderedSet(URITemplate(uri).variable_names)

