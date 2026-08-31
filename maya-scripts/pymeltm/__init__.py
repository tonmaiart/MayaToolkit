"""Facade for a vendored PyMEL, importable as `pymeltm` instead of `pymel`.

Maya installs on studio machines don't reliably ship PyMEL, and even when
they do, its version may not match this vendored one -- so this vendors
pymel 1.5.0 (LumaPictures, from PyPI) under vendor/pymel/ and exposes it
under a distinct top-level name that never collides with a real `pymel`
some other tool or a different Maya install might provide.

vendor/ is intentionally NOT on the shared MayaToolkit PYTHONPATH, so a bare
`import pymel` elsewhere is unaffected by this. PyMEL's own modules
cross-import each other as absolute `pymel.xxx` though, and rewriting those
across its whole source tree isn't practical -- so internally we still
import it under its real name (after pointing sys.path at vendor/) and then
alias every `pymel`/`pymel.*` module already sitting in sys.modules to the
matching `pymeltm`/`pymeltm.*` key. That makes `import pymeltm.core as pm`
resolve to the *same* module object pymel's own internals use, rather than
re-executing (and duplicating) it under a second identity.

Usage: `import pymeltm.core as pm` wherever code used to `import pymel.core as pm`.
"""

import os
import sys

_VENDOR_DIR = os.path.join(os.path.dirname(__file__), "vendor")

if _VENDOR_DIR not in sys.path:
    sys.path.insert(0, _VENDOR_DIR)

import pymel as _pymel  # noqa: E402  (real internal name -- required for pymel's own cross-imports)

for _name, _module in list(sys.modules.items()):
    if _name == "pymel" or _name.startswith("pymel."):
        sys.modules["pymeltm" + _name[len("pymel"):]] = _module

# Replace this in-progress module with the real pymel module object so
# `import pymeltm as pm` behaves exactly like `import pymel as pm` would.
sys.modules[__name__] = _pymel
