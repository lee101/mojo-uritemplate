from __future__ import annotations

from collections.abc import Iterable, MutableSet


class OrderedSet(MutableSet[str]):
    """A mutable set that iterates in insertion order."""

    def __init__(self, iterable: Iterable[str] | None = None):
        self._items: dict[str, None] = {}
        if iterable is not None:
            self |= iterable

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, key: object) -> bool:
        return key in self._items

    def add(self, key: str) -> None:
        self._items[key] = None

    def discard(self, key: str) -> None:
        self._items.pop(key, None)

    def __iter__(self):
        return iter(self._items)

    def __reversed__(self):
        return reversed(self._items)

    def pop(self, last: bool = True) -> str:
        if not self:
            raise KeyError("set is empty")
        key = next(reversed(self)) if last else next(iter(self))
        self.discard(key)
        return key

    def __repr__(self) -> str:
        if not self:
            return f"{self.__class__.__name__}()"
        return f"{self.__class__.__name__}({list(self)!r})"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        if isinstance(other, OrderedSet):
            return list(self) == list(other)
        if isinstance(other, set):
            return set(self) == other
        return NotImplemented

