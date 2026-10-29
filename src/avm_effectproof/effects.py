"""Application-effect proofs for the AVM — Algorand and Voi.

A State Proof commits to block headers; a block header commits to a Merkle tree
whose leaves are `SignedTxnInBlock` values **including their ApplyData**
(go-algorand `data/bookkeeping/txn_merkle.go`: "a cryptographic commitment to the
transactions in the block, along with their ApplyData"). ApplyData carries the
EvalDelta: global/local state deltas, logs and inner transactions.

So once a transaction is proven into a block, its *effects* are proven with it.
This package reads those effects out of an authenticated STIB and answers
questions about them. It does not authenticate anything itself — feed it an STIB
that `avm-proofpack` (or any equivalent verifier) has already proven, and it will
tell you what the transaction actually did.

Algorand and Voi share the AVM block and transaction encoding, so one
implementation covers both; a `ChainProfile` only records which chain a fixture
came from.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__version__ = "0.1.1"

__all__ = [
    "ALGORAND_MAINNET",
    "VOI_MAINNET",
    "ChainProfile",
    "EffectError",
    "Effects",
    "InnerTxn",
    "StateChange",
    "decode_stib",
]


class EffectError(ValueError):
    """Malformed or unreadable SignedTxnInBlock."""


@dataclass(frozen=True)
class ChainProfile:
    """Identifies the chain a fixture belongs to. Not a trust anchor."""

    name: str
    genesis_id: str


ALGORAND_MAINNET = ChainProfile(name="algorand-mainnet", genesis_id="mainnet-v1.0")
VOI_MAINNET = ChainProfile(name="voi-mainnet", genesis_id="voimain-v1.0")


@dataclass(frozen=True)
class StateChange:
    """One key/value write, or a deletion.

    ``value`` is ``bytes`` for a byte-slice write, ``int`` for a uint write, and
    ``None`` for a deletion. go-algorand encodes these as a ``ValueDelta`` with
    ``at`` in {1 = set bytes, 2 = set uint, 3 = delete} (``data/basics/teal.go``);
    the enum is 1-based and 0 is not a valid action.
    """

    key: bytes
    value: bytes | int | None

    @property
    def is_delete(self) -> bool:
        return self.value is None


@dataclass(frozen=True)
class InnerTxn:
    """An inner transaction and its own effects."""

    txn_type: str
    sender: bytes
    receiver: bytes | None
    amount: int
    asset_id: int
    asset_amount: int
    app_id: int
    effects: Effects


@dataclass(frozen=True)
class Effects:
    """The decoded effects of one top-level transaction."""

    chain: str
    txn_type: str
    sender: bytes
    receiver: bytes | None
    amount: int
    asset_id: int
    asset_amount: int
    app_id: int
    global_changes: tuple[StateChange, ...]
    local_deltas: tuple[tuple[int, tuple[StateChange, ...]], ...]
    logs: tuple[bytes, ...]
    inner: tuple[InnerTxn, ...]
    created_app_id: int
    created_asset_id: int
    closing_amount: int
    asset_closing_amount: int

    # -- convenience -----------------------------------------------------

    def all_inner(self) -> tuple[InnerTxn, ...]:
        """Every inner transaction at any depth, parents before children."""
        out: list[InnerTxn] = []
        for child in self.inner:
            out.append(child)
            out.extend(child.effects.all_inner())
        return tuple(out)

    def all_logs(self) -> tuple[bytes, ...]:
        out = list(self.logs)
        for child in self.all_inner():
            out.extend(child.effects.logs)
        return tuple(out)

    def all_global_changes(self) -> tuple[StateChange, ...]:
        out = list(self.global_changes)
        for child in self.all_inner():
            out.extend(child.effects.global_changes)
        return tuple(out)

    def max_depth(self) -> int:
        return 0 if not self.inner else 1 + max(c.effects.max_depth() for c in self.inner)


def _as_bytes(value: Any, what: str) -> bytes:
    """Coerce a binary field, tolerating msgpack's str-with-surrogates form.

    The same logical field arrives as ``bytes`` on one chain and as a
    surrogate-escaped ``str`` on the other, so both are accepted and
    round-tripped to the original bytes.
    """
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8", "surrogateescape")
    raise EffectError(f"{what} must be bytes, got {type(value).__name__}")


def _as_int(value: Any, default: int = 0) -> int:
    return value if type(value) is int else default


def _as_str(value: Any, default: str = "") -> str:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("ascii", "replace")
    return value if isinstance(value, str) else default


_SET_BYTES = 1
_SET_UINT = 2
_DELETE = 3


def _state_changes(delta: Any, what: str) -> tuple[StateChange, ...]:
    """Decode a StateDelta of ``ValueDelta`` entries.

    Each value is ``{"at": action, "bs": <str>, "ui": <uint>}`` where the action
    is 1 = set bytes, 2 = set uint, 3 = delete. ``bs``/``ui`` are omitted when
    empty, so a set-uint of 0 arrives as ``{"at": 2}``. Any other shape is
    malformed and raises rather than guessing.
    """
    if delta is None:
        return ()
    if not isinstance(delta, dict):
        raise EffectError(f"{what} must be a mapping")
    out: list[StateChange] = []
    for key, value in delta.items():
        kb = key if isinstance(key, (bytes, bytearray)) else str(key).encode("utf-8", "surrogateescape")
        if not isinstance(value, dict):
            raise EffectError(f"{what} value must be a ValueDelta mapping")
        action = value.get("at")
        if action == _SET_BYTES:
            raw = value.get("bs", "")
            if not isinstance(raw, (str, bytes, bytearray)):
                raise EffectError(f"{what} byte value must be str or bytes")
            # msgpack decodes arbitrary binary as str with surrogate escapes, so
            # round-trip with surrogateescape to recover the original bytes.
            encoded = raw.encode("utf-8", "surrogateescape") if isinstance(raw, str) else bytes(raw)
            out.append(StateChange(key=bytes(kb), value=encoded))
        elif action == _SET_UINT:
            uint = value.get("ui", 0)
            if type(uint) is not int or uint < 0:
                raise EffectError(f"{what} uint value must be a non-negative int")
            out.append(StateChange(key=bytes(kb), value=uint))
        elif action == _DELETE:
            out.append(StateChange(key=bytes(kb), value=None))
        else:
            raise EffectError(f"{what} has an unrecognised action {action!r}")
    return tuple(sorted(out, key=lambda c: c.key))


def _decode_eval_delta(stib: dict, chain: str) -> dict:
    """Pull the EvalDelta out of a STIB.

    go-algorand flattens ApplyData into the STIB, so the EvalDelta fields
    (``gd``/``ld``/``lg``/``itx``) sit directly under the ``dt`` key.
    """
    delta = stib.get("dt")
    if delta is None:
        return {}
    if not isinstance(delta, dict):
        raise EffectError("ApplyData must be a mapping")
    return delta


def _effects_from(stib: Any, chain: str, depth: int = 0) -> Effects:
    if not isinstance(stib, dict):
        raise EffectError("SignedTxnInBlock must be a mapping")
    if depth > 8:
        raise EffectError("inner transaction nesting is too deep")
    txn = stib.get("txn")
    if not isinstance(txn, dict):
        raise EffectError("SignedTxnInBlock is missing its transaction")

    delta = _decode_eval_delta(stib, chain)
    global_changes = _state_changes(delta.get("gd"), "global delta")

    local: list[tuple[int, tuple[StateChange, ...]]] = []
    raw_local = delta.get("ld")
    if raw_local is not None:
        if not isinstance(raw_local, dict):
            raise EffectError("local deltas must be a mapping")
        for index, sub in raw_local.items():
            if type(index) is not int:
                raise EffectError("local delta index must be an int")
            local.append((index, _state_changes(sub, "local delta")))

    logs: list[bytes] = []
    for entry in delta.get("lg") or ():
        logs.append(_as_bytes(entry, "log entry"))

    inner: list[InnerTxn] = []
    for child in delta.get("itx") or ():
        child_effects = _effects_from(child, chain, depth + 1)
        inner.append(
            InnerTxn(
                txn_type=child_effects.txn_type,
                sender=child_effects.sender,
                receiver=child_effects.receiver,
                amount=child_effects.amount,
                asset_id=child_effects.asset_id,
                asset_amount=child_effects.asset_amount,
                app_id=child_effects.app_id,
                effects=child_effects,
            )
        )

    return Effects(
        chain=chain,
        txn_type=_as_str(txn.get("type")),
        sender=_as_bytes(txn.get("snd"), "sender") if txn.get("snd") is not None else b"",
        receiver=_as_bytes(txn["rcv"], "receiver") if txn.get("rcv") is not None else None,
        amount=_as_int(txn.get("amt")),
        asset_id=_as_int(txn.get("xaid")),
        asset_amount=_as_int(txn.get("aamt")),
        app_id=_as_int(txn.get("apid")),
        global_changes=global_changes,
        local_deltas=tuple(sorted(local, key=lambda p: p[0])),
        logs=tuple(logs),
        inner=tuple(inner),
        # ca/aca/caid/apid are ApplyData fields, siblings of the EvalDelta (dt),
        # NOT inside it (go-algorand data/transactions/teal.go: ApplyData embeds
        # EvalDelta under "dt" alongside these). Read them from the STIB level.
        created_app_id=_as_int(stib.get("apid")),
        created_asset_id=_as_int(stib.get("caid")),
        closing_amount=_as_int(stib.get("ca")),
        asset_closing_amount=_as_int(stib.get("aca")),
    )


def decode_stib(stib: bytes, *, chain: ChainProfile = ALGORAND_MAINNET) -> Effects:
    """Decode an already-authenticated ``SignedTxnInBlock`` into its effects.

    ``stib`` must be the msgpack encoding of the STIB as it appears in the block
    (i.e. the leaf the block's transaction Merkle tree commits to). This function
    does NOT verify inclusion — pass it a STIB you have proven, or the effects
    are just claims.
    """
    if not isinstance(stib, (bytes, bytearray)):
        raise EffectError("stib must be bytes")
    from avm_proofpack import mpack

    try:
        decoded = mpack.decode(bytes(stib))
    except Exception as exc:
        raise EffectError(f"stib is not valid msgpack: {exc}") from exc
    return _effects_from(decoded, chain.name)
