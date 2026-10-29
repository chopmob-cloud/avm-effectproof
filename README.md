# avm-effectproof

**Application-effect proofs for Algorand and Voi.** Read what a transaction
*actually did* — inner transactions, logs, global and local state changes — out
of a `SignedTxnInBlock` you have already proven into a block.

One implementation covers **both chains**: Algorand and Voi share the AVM block
and transaction encoding.

## Why this exists

A State Proof commits to block headers. A block header commits to a transaction
Merkle tree. In go-algorand (`data/bookkeeping/txn_merkle.go`) that tree is *"a
cryptographic commitment to the transactions in the block, **along with their
ApplyData**"* — and `ApplyData` carries the `EvalDelta`:

| Field | Meaning |
|---|---|
| `gd` | global state changes |
| `ld` | local state changes |
| `lg` | emitted logs |
| `itx` | **inner transactions**, each with its own `ApplyData` |

So once a transaction is proven into a block, its effects are proven with it.
This library reads those effects. It does **not** authenticate anything: feed it
a STIB that [`avm-proofpack`](https://github.com/chopmob-cloud/avm-proofpack) has
already proven, or the effects are just claims.

## Install

```bash
pip install avm-effectproof
```

## Use

```python
from avm_effectproof import decode_stib, VOI_MAINNET, has_log, has_inner, has_global_state

effects = decode_stib(stib_bytes, chain=VOI_MAINNET)   # STIB you already proved

effects.app_id                       # 5211
[entry.hex() for entry in effects.logs]
len(effects.all_inner())             # inner txns at every depth

has_log(effects, prefix=b"\x80U")
has_inner(effects, txn_type="pay")
has_global_state(effects, key=b"total_transactions")
```

`decode_stib` searches inner transactions recursively; `effects.all_inner()` is
flat and ordered parents-before-children.

### CLI

```bash
avm-effectproof stib.bin --chain voi --describe
avm-effectproof stib.bin --chain algorand --inner-type pay
avm-effectproof stib.bin --global-key pendingCost --global-value 36000
```

Exit codes: `0` pass, `1` a check failed, `2` input error.

## State change encoding (do not guess this)

`ValueDelta` is `{"at": action, "bs": <str>, "ui": <uint>}` and the action enum
is **1-based** (`data/basics/teal.go`):

| `at` | action |
|---|---|
| 1 | set bytes (`bs`) |
| 2 | set uint (`ui`) |
| 3 | delete |

`0` is not valid, and `bs`/`ui` are omitted when empty — a set-uint of `0`
arrives as `{"at": 2}`. The decoder raises on anything else rather than guessing.

Binary fields arrive as `bytes` on one chain and as surrogate-escaped `str` on
the other; both are round-tripped to the original bytes with `surrogateescape`.

## Verified against real chain data

Both fixtures are real blocks, committed to the test suite:

| Chain | Round | Contents |
|---|---|---|
| Algorand mainnet | 63605124 | app 1439234347, 2 global writes, 3 inner (incl. a 1000 µAlgo payment) |
| Voi mainnet | 181248 | app 5211, 2 logs, 5 inner (incl. a 100000 µVoi payment) |

Every structural test runs against **both** chains.

## What this does not do

- It does not prove inclusion. Pair it with `avm-proofpack`.
- It does not resolve local-state delta account indices; `ld` keys are exposed as
  the raw indices used by `EvalDelta`.
- It does not decode application arguments, boxes or asset holdings.

## Licence

Apache-2.0.
