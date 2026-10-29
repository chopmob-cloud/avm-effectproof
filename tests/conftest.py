"""Ensure the tests exercise THIS checkout, not another avm_effectproof."""
import sys
from pathlib import Path

_SRC = (Path(__file__).resolve().parent.parent / "src").resolve()
_SRC_STR = str(_SRC)

if _SRC_STR in sys.path:
    sys.path.remove(_SRC_STR)
sys.path.insert(0, _SRC_STR)

for _name in [m for m in list(sys.modules) if m == "avm_effectproof" or m.startswith("avm_effectproof.")]:
    del sys.modules[_name]

import avm_effectproof

_origin = Path(avm_effectproof.__file__).resolve()
if _SRC not in _origin.parents:
    raise RuntimeError(
        f"tests are importing avm_effectproof from {_origin}, not from this checkout ({_SRC})"
    )
