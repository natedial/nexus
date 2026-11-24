"""Group debate arguments into threads and choose which threads to show."""

from __future__ import annotations

from collections import defaultdict
from itertools import zip_longest
from typing import Any, Sequence


def select_thread_arguments(arguments: Sequence[Any], limit: int) -> list[Any]:
    """Pick up to ``limit`` arguments without splitting a challenge from its reply.

    Challenged and unchallenged claims alternate so neither kind crowds out the
    other. A claim that was challenged is never shown as if it were not, unless
    nothing else fits.
    """
    if len(arguments) <= limit:
        return list(arguments)
    known = {_get(item, "argument_id") for item in arguments}
    children: dict[str, list[Any]] = defaultdict(list)
    roots: list[Any] = []
    for item in arguments:
        target = _get(item, "target_claim_id")
        if target in known and target != _get(item, "argument_id"):
            children[target].append(item)
        else:
            roots.append(item)

    challenged = [root for root in roots if children[_get(root, "argument_id")]]
    unchallenged = [root for root in roots if not children[_get(root, "argument_id")]]
    selected: list[Any] = []
    for pair in zip_longest(challenged, unchallenged):
        for root in pair:
            remaining = limit - len(selected)
            if root is None or remaining <= 0:
                continue
            branches = [
                _flatten(child, children) for child in children[_get(root, "argument_id")]
            ]
            fitting: list[Any] = []
            for branch in branches:
                if 1 + len(fitting) + len(branch) <= remaining:
                    fitting.extend(branch)
            if branches and not fitting and selected:
                continue
            selected.extend([root, *fitting])
    return selected


def _flatten(item: Any, children: dict[str, list[Any]]) -> list[Any]:
    ordered: list[Any] = []
    stack = [item]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        ordered.append(current)
        stack.extend(reversed(children[_get(current, "argument_id")]))
    return ordered


def _get(item: Any, name: str) -> Any:
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)
