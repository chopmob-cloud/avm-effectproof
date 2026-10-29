"""CLI: describe or check the effects of an authenticated STIB.

Exit codes: 0 = described / all checks passed, 1 = a check failed, 2 = input error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .effects import ALGORAND_MAINNET, VOI_MAINNET, EffectError, Effects, decode_stib
from .predicates import find_inner, find_logs, has_global_state, has_inner, has_log

CHAINS = {"algorand": ALGORAND_MAINNET, "voi": VOI_MAINNET}


def _effects_to_dict(effects: Effects) -> dict:
    return {
        "chain": effects.chain,
        "txn_type": effects.txn_type,
        "sender": effects.sender.hex(),
        "receiver": effects.receiver.hex() if effects.receiver else None,
        "amount": effects.amount,
        "asset_id": effects.asset_id,
        "asset_amount": effects.asset_amount,
        "app_id": effects.app_id,
        "created_app_id": effects.created_app_id,
        "created_asset_id": effects.created_asset_id,
        "logs": [entry.hex() for entry in effects.logs],
        "global_changes": [
            {"key": c.key.hex(), "key_text": c.key.decode("utf-8", "replace"),
             "value": c.value.hex() if isinstance(c.value, bytes) else c.value,
             "deleted": c.is_delete}
            for c in effects.global_changes
        ],
        "local_deltas": [
            {"index": index,
             "changes": [{"key": c.key.hex(),
                          "value": c.value.hex() if isinstance(c.value, bytes) else c.value,
                          "deleted": c.is_delete} for c in changes]}
            for index, changes in effects.local_deltas
        ],
        "inner": [
            {
                "txn_type": child.txn_type,
                "sender": child.sender.hex(),
                "receiver": child.receiver.hex() if child.receiver else None,
                "amount": child.amount,
                "asset_id": child.asset_id,
                "asset_amount": child.asset_amount,
                "app_id": child.app_id,
                "logs": [entry.hex() for entry in child.effects.logs],
            }
            for child in effects.all_inner()
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="avm-effectproof",
        description="Read application effects out of an authenticated SignedTxnInBlock.",
    )
    parser.add_argument("file", type=Path, help="msgpack SignedTxnInBlock (already proven)")
    parser.add_argument("--chain", choices=sorted(CHAINS), default="algorand")
    parser.add_argument("--describe", action="store_true", help="print effects as JSON")
    parser.add_argument("--log-prefix", help="require a log starting with this hex prefix")
    parser.add_argument("--inner-type", help="require an inner transaction of this type")
    parser.add_argument("--global-key", help="require a write to this global key (utf-8)")
    parser.add_argument("--global-value", help="require this uint value for --global-key")
    args = parser.parse_args(argv)

    try:
        effects = decode_stib(args.file.read_bytes(), chain=CHAINS[args.chain])
    except (OSError, EffectError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.describe or not any((args.log_prefix, args.inner_type, args.global_key)):
        print(json.dumps(_effects_to_dict(effects), indent=2))
        return 0

    failures: list[str] = []
    if args.log_prefix:
        prefix = bytes.fromhex(args.log_prefix)
        if not has_log(effects, prefix=prefix):
            failures.append(f"no log with prefix {args.log_prefix}")
    if args.inner_type and not has_inner(effects, txn_type=args.inner_type):
        failures.append(f"no inner transaction of type {args.inner_type}")
    if args.global_key:
        key = args.global_key.encode()
        value = int(args.global_value) if args.global_value is not None else None
        if not has_global_state(effects, key=key, value=value):
            failures.append(f"no global write to {args.global_key}")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1

    print(f"OK: {len(find_logs(effects))} logs, "
          f"{len(find_inner(effects))} inner transactions, "
          f"{len(effects.global_changes)} global changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
