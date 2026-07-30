from __future__ import annotations

import re
import collections.abc
from typing import Any

from ._lib import expand_native
from .orderedset import OrderedSet

template_re = re.compile(r"{([^}]+)}")
_OPERATORS = "+#./;?&=,!@|"


def _merge(var_dict, overrides):
    if var_dict:
        if not overrides:
            return var_dict
        options = var_dict.copy()
        options.update(overrides)
        return options
    return overrides


def _is_pairs(value):
    return bool(value) and isinstance(value, (list, tuple)) and all(
        isinstance(item, tuple) and len(item) == 2 for item in value
    )


class URIVariable:
    """Parsed metadata for one expression in a URI template."""

    def __init__(self, var: str):
        self.original = var
        self.operator = var[0] if var[0] in _OPERATORS else ""
        variable_list = var[1:] if self.operator else var
        self.variables: list[tuple[str, dict[str, Any]]] = []
        self.defaults: dict[str, Any] = {}
        for spec in variable_list.split(","):
            default = None
            name = spec
            if "=" in spec:
                name, default = spec.split("=", 1)
            explode = name.endswith("*")
            name = name.rstrip("*")
            prefix = None
            if ":" in name:
                name, prefix_text = name.split(":", 1)
                prefix = int(prefix_text, 10)
            if default:
                self.defaults[name] = default
            self.variables.append(
                (name, {"explode": explode, "prefix": prefix})
            )
        self.variable_names = [name for name, _ in self.variables]

    def __str__(self) -> str:
        return self.original

    def __repr__(self) -> str:
        return f"URIVariable({self})"

    def expand(self, var_dict=None):
        if var_dict is None:
            return {self.original: self.original}
        return {
            self.original: expand_native(
                "{" + self.original + "}", var_dict, False
            )
        }


class URITemplate:
    """Parse and expand an RFC 6570 URI template."""

    def __init__(self, uri: str):
        self.uri = uri
        self._uri_bytes = uri.encode()
        self.variables = [
            URIVariable(match.group(1)) for match in template_re.finditer(uri)
        ]
        self.variable_names = OrderedSet()
        self._prefixes = []
        for variable in self.variables:
            for name in variable.variable_names:
                self.variable_names.add(name)
            for name, options in variable.variables:
                if options["prefix"]:
                    self._prefixes.append(
                        (variable.operator, variable.defaults, name, options["prefix"])
                    )

    def __repr__(self) -> str:
        return f'URITemplate("{self}")'

    def __str__(self) -> str:
        return self.uri

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, URITemplate):
            return NotImplemented
        return self.uri == other.uri

    def __hash__(self) -> int:
        return hash(self.uri)

    def expand(self, var_dict=None, **kwargs) -> str:
        values = _merge(var_dict, kwargs)
        self._validate_prefixes(values)
        return expand_native(self._uri_bytes, values, False)

    def partial(self, var_dict=None, **kwargs) -> "URITemplate":
        values = _merge(var_dict, kwargs)
        self._validate_prefixes(values)
        return URITemplate(
            expand_native(self._uri_bytes, values, True)
        )

    def _validate_prefixes(self, values) -> None:
        for operator, defaults, name, prefix in self._prefixes:
            value = values.get(name, None)
            if not value and value != "" and name in defaults:
                value = defaults[name]
            if value is None:
                continue
            composite = (
                isinstance(value, (list, tuple))
                and not _is_pairs(value)
            ) or isinstance(value, collections.abc.MutableMapping) or _is_pairs(value)
            if composite:
                continue
            if operator in ("?", "&") and not value:
                continue
            sliced = value[:prefix]
            if isinstance(sliced, bytes):
                sliced.decode()
