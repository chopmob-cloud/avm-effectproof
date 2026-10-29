"""Dual-chain effect decoding. Every structural test runs on BOTH chains."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from avm_effectproof import (
    ALGORAND_MAINNET,
    VOI_MAINNET,
    EffectError,
    decode_stib,
    find_inner,
    find_logs,
    has_global_state,
    has_inner,
    has_log,
)

FIXTURES = Path(__file__).parent / "fixtures"

CASES = [
    ("algorand", ALGORAND_MAINNET, "stib_algorand_mainnet"),
    ("voi", VOI_MAINNET, "stib_voi_mainnet"),
]


def _load(stem: str) -> bytes:
    return (FIXTURES / f"{stem}.bin").read_bytes()


def _meta(stem: str) -> dict:
    return json.loads((FIXTURES / f"{stem}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name,chain,stem", CASES, ids=[c[0] for c in CASES])
def test_decodes_real_chain_data(name, chain, stem):
    effects = decode_stib(_load(stem), chain=chain)
    meta = _meta(stem)

    assert effects.chain == chain.name
    assert effects.txn_type == "appl"
    # every effect count must match what the block actually contained
    assert len(effects.all_inner()) == meta["n_inner"]
    assert len(effects.logs) == meta["n_logs"]
    assert len(effects.global_changes) == meta["n_gd"]
    assert len(effects.local_deltas) == meta["n_ld"]


@pytest.mark.parametrize("name,chain,stem", CASES, ids=[c[0] for c in CASES])
def test_sender_is_a_32_byte_address(name, chain, stem):
    effects = decode_stib(_load(stem), chain=chain)
    assert isinstance(effects.sender, bytes)
    assert len(effects.sender) == 32


def test_algorand_fixture_specifics():
    effects = decode_stib(_load("stib_algorand_mainnet"), chain=ALGORAND_MAINNET)
    assert effects.app_id == 1439234347

    # real global state written by the call
    assert has_global_state(effects, key=b"lastPriceRound", value=63605124)
    assert has_global_state(effects, key=b"pendingCost", value=36000)
    assert not has_global_state(effects, key=b"pendingCost", value=1)

    # 2 inner app calls to 1284326447 plus one native payment of 1000
    assert len(find_inner(effects, app_id=1284326447)) == 2
    pays = find_inner(effects, txn_type="pay")
    assert len(pays) == 1
    assert pays[0][1].amount == 1000

    # inner app calls carry their own global deltas
    inner_app = find_inner(effects, app_id=1284326447)[0][1]
    assert has_global_state(inner_app, key=b"total_transactions")


def test_voi_fixture_specifics():
    effects = decode_stib(_load("stib_voi_mainnet"), chain=VOI_MAINNET)
    assert effects.app_id == 5211

    # two logs on the outer call, all binary
    assert len(effects.logs) == 2
    assert all(isinstance(entry, bytes) for entry in effects.logs)
    assert all(len(entry) > 0 for entry in effects.logs)

    # five inner transactions, one of which is a 100000 micro payment
    assert len(effects.all_inner()) == 5
    pays = find_inner(effects, txn_type="pay")
    assert len(pays) == 1
    assert pays[0][1].amount == 100000

    # three inner app calls each emitted a log
    inner_logs = [c for c in effects.all_inner() if c.effects.logs]
    assert len(inner_logs) == 3


def test_created_app_id_is_read_from_applydata_not_eval_delta():
    """Regression: ca/aca/caid/apid are ApplyData fields (siblings of the
    EvalDelta ``dt``), not inside it. The Voi block's first inner transaction
    really created app 36929; reading these from ``dt`` silently reports 0,
    which under-reports a real effect."""
    effects = decode_stib(_load("stib_voi_mainnet"), chain=VOI_MAINNET)
    creators = [c for c in effects.all_inner() if c.effects.created_app_id]
    assert len(creators) == 1
    assert creators[0].effects.created_app_id == 36929


@pytest.mark.parametrize("name,chain,stem", CASES, ids=[c[0] for c in CASES])
def test_created_and_closing_fields_default_to_zero_when_absent(name, chain, stem):
    """When the ApplyData carries no creation/close-out, the fields read 0 —
    not an exception, and not a stale value pulled from the wrong map."""
    effects = decode_stib(_load(stem), chain=chain)
    assert effects.created_asset_id == 0
    assert effects.closing_amount == 0
    assert effects.asset_closing_amount == 0


def test_applydata_fields_are_decoded_from_the_stib_level():
    """Synthetic STIB exercising all four ApplyData effect fields at once, with
    decoy values inside the EvalDelta to prove they are not read from there."""
    from avm_proofpack import mpack

    stib = {
        "txn": {"type": "acfg", "snd": b"\x01" * 32},
        "ca": 7000,
        "aca": 42,
        "apid": 555,
        "caid": 999,
        "dt": {"apid": 111, "caid": 222, "ca": 333, "aca": 444},  # decoys in dt
    }
    effects = decode_stib(mpack.encode_canonical(stib), chain=ALGORAND_MAINNET)
    assert effects.created_app_id == 555
    assert effects.created_asset_id == 999
    assert effects.closing_amount == 7000
    assert effects.asset_closing_amount == 42


@pytest.mark.parametrize("name,chain,stem", CASES, ids=[c[0] for c in CASES])
def test_log_predicates_are_binary_safe(name, chain, stem):
    effects = decode_stib(_load(stem), chain=chain)
    # every log must be findable by its own exact bytes
    for _path, entry in find_logs(effects):
        assert has_log(effects, exact=entry)
    # and a prefix of a real log must match
    if effects.logs:
        assert has_log(effects, prefix=effects.logs[0][:2])
    assert not has_log(effects, exact=b"\x00" * 64)


@pytest.mark.parametrize("name,chain,stem", CASES, ids=[c[0] for c in CASES])
def test_inner_transactions_are_findable(name, chain, stem):
    effects = decode_stib(_load(stem), chain=chain)
    assert has_inner(effects)
    assert has_inner(effects, txn_type="pay")
    # a type that is not present must not match
    assert not has_inner(effects, txn_type="axfer")


# -- fail-closed -------------------------------------------------------


def test_rejects_non_bytes():
    with pytest.raises(EffectError):
        decode_stib("not bytes")


def test_rejects_garbage_msgpack():
    with pytest.raises(EffectError):
        decode_stib(b"\xc1\xc1\xc1")


def test_rejects_stib_without_transaction():
    from avm_proofpack import mpack

    with pytest.raises(EffectError):
        decode_stib(mpack.encode_canonical({"dt": {}}))


def test_rejects_unknown_state_action():
    from avm_proofpack import mpack

    bad = {"txn": {"type": "appl", "snd": b"\x00" * 32},
           "dt": {"gd": {"k": {"at": 99}}}}
    with pytest.raises(EffectError):
        decode_stib(mpack.encode_canonical(bad))


def test_rejects_action_zero_because_enum_is_one_based():
    """go-algorand's DeltaAction starts at 1; 0 is not a valid action."""
    from avm_proofpack import mpack

    bad = {"txn": {"type": "appl", "snd": b"\x00" * 32},
           "dt": {"gd": {"k": {"at": 0, "ui": 1}}}}
    with pytest.raises(EffectError):
        decode_stib(mpack.encode_canonical(bad))


def test_rejects_excessive_inner_nesting():
    from avm_proofpack import mpack

    node = {"txn": {"type": "appl", "snd": b"\x00" * 32}, "dt": {}}
    for _ in range(12):
        node = {"txn": {"type": "appl", "snd": b"\x00" * 32}, "dt": {"itx": [node]}}
    with pytest.raises(EffectError):
        decode_stib(mpack.encode_canonical(node))
