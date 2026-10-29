"""Predicates over decoded effects.

Each predicate answers a question a counterparty would actually ask ("did this
call transfer 5 USDC to me?", "did it emit this log?") against effects that came
out of an authenticated STIB. They search the top-level transaction and, by
default, every inner transaction at any depth.
"""
from __future__ import annotations

from .effects import Effects, StateChange

__all__ = [
    "find_asset_transfers",
    "find_global_changes",
    "find_inner",
    "find_logs",
    "find_payments",
    "has_asset_transfer",
    "has_global_state",
    "has_inner",
    "has_log",
    "has_payment",
]


def _candidates(effects: Effects, include_inner: bool) -> list[tuple[str, Effects]]:
    """Top-level first, then each inner transaction with a path label."""
    out: list[tuple[str, Effects]] = [("top", effects)]
    if include_inner:
        for index, child in enumerate(effects.all_inner()):
            out.append((f"inner[{index}]", child.effects))
    return out


def find_asset_transfers(
    effects: Effects,
    *,
    asset_id: int | None = None,
    amount: int | None = None,
    receiver: bytes | None = None,
    sender: bytes | None = None,
    include_inner: bool = True,
) -> list[tuple[str, Effects]]:
    """Every asset transfer (``axfer``) matching the given constraints."""
    hits: list[tuple[str, Effects]] = []
    for path, node in _candidates(effects, include_inner):
        if node.txn_type != "axfer":
            continue
        if asset_id is not None and node.asset_id != asset_id:
            continue
        if amount is not None and node.asset_amount != amount:
            continue
        if receiver is not None and node.receiver != receiver:
            continue
        if sender is not None and node.sender != sender:
            continue
        hits.append((path, node))
    return hits


def find_payments(
    effects: Effects,
    *,
    amount: int | None = None,
    receiver: bytes | None = None,
    sender: bytes | None = None,
    include_inner: bool = True,
) -> list[tuple[str, Effects]]:
    """Every native payment (``pay``) matching the given constraints."""
    hits: list[tuple[str, Effects]] = []
    for path, node in _candidates(effects, include_inner):
        if node.txn_type != "pay":
            continue
        if amount is not None and node.amount != amount:
            continue
        if receiver is not None and node.receiver != receiver:
            continue
        if sender is not None and node.sender != sender:
            continue
        hits.append((path, node))
    return hits


def find_logs(
    effects: Effects,
    *,
    exact: bytes | None = None,
    prefix: bytes | None = None,
    include_inner: bool = True,
) -> list[tuple[str, bytes]]:
    """Every emitted log, optionally filtered by exact value or prefix."""
    hits: list[tuple[str, bytes]] = []
    for path, node in _candidates(effects, include_inner):
        for entry in node.logs:
            if exact is not None and entry != exact:
                continue
            if prefix is not None and not entry.startswith(prefix):
                continue
            hits.append((path, entry))
    return hits


def find_global_changes(
    effects: Effects,
    *,
    key: bytes | None = None,
    include_inner: bool = True,
) -> list[tuple[str, StateChange]]:
    """Every global state change, optionally filtered by key."""
    hits: list[tuple[str, StateChange]] = []
    for path, node in _candidates(effects, include_inner):
        for change in node.global_changes:
            if key is not None and change.key != key:
                continue
            hits.append((path, change))
    return hits


def find_inner(
    effects: Effects,
    *,
    txn_type: str | None = None,
    app_id: int | None = None,
) -> list[tuple[str, Effects]]:
    """Inner transactions, optionally filtered by type or target app id."""
    hits: list[tuple[str, Effects]] = []
    for index, child in enumerate(effects.all_inner()):
        if txn_type is not None and child.txn_type != txn_type:
            continue
        if app_id is not None and child.app_id != app_id:
            continue
        hits.append((f"inner[{index}]", child.effects))
    return hits


# -- boolean forms -------------------------------------------------------


def has_asset_transfer(effects: Effects, **kwargs) -> bool:
    return bool(find_asset_transfers(effects, **kwargs))


def has_payment(effects: Effects, **kwargs) -> bool:
    return bool(find_payments(effects, **kwargs))


def has_log(effects: Effects, **kwargs) -> bool:
    return bool(find_logs(effects, **kwargs))


def has_global_state(effects: Effects, *, key: bytes, value: bytes | None = None,
                     deleted: bool = False, **kwargs) -> bool:
    """True when ``key`` was written to ``value`` (or deleted when ``deleted``).

    ``value=None`` with ``deleted=False`` means "any write", so the caller can
    ask "was this key touched?" without pinning the value.
    """
    for _path, change in find_global_changes(effects, key=key, **kwargs):
        if deleted:
            if change.is_delete:
                return True
            continue
        if change.is_delete:
            continue
        if value is None or change.value == value:
            return True
    return False


def has_inner(effects: Effects, **kwargs) -> bool:
    return bool(find_inner(effects, **kwargs))
