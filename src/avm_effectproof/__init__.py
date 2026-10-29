"""avm-effectproof — application-effect proofs for Algorand and Voi.

Feed it a `SignedTxnInBlock` you have already proven into a block (for example
with `avm-proofpack`), and it tells you what the transaction actually did:
inner transactions, logs, global and local state changes.

Algorand and Voi share the AVM block and transaction encoding, so one
implementation serves both.
"""
from __future__ import annotations

from .effects import (
    ALGORAND_MAINNET,
    VOI_MAINNET,
    ChainProfile,
    EffectError,
    Effects,
    InnerTxn,
    StateChange,
    decode_stib,
)
from .predicates import (
    find_asset_transfers,
    find_global_changes,
    find_inner,
    find_logs,
    find_payments,
    has_asset_transfer,
    has_global_state,
    has_inner,
    has_log,
    has_payment,
)

__version__ = "0.1.0"

__all__ = [
    "ALGORAND_MAINNET",
    "VOI_MAINNET",
    "ChainProfile",
    "EffectError",
    "Effects",
    "InnerTxn",
    "StateChange",
    "__version__",
    "decode_stib",
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
