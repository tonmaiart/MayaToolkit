"""Facade namespace for a vendored, pymel-compatible API, importable as
`pymeltm` instead of `pymel` so it never collides with a real `pymel` some
other tool or Maya install might provide.

`pymeltm.core` is `mgear.pymaya` (from mGear 5.3.3, MIT licensed -- see
core/LICENSE-mgear.txt) vendored under this name. Unlike real PyMEL, it has
no offline-docs or per-Maya-version apicache dependency at all: at import
time it just wraps every callable already present on the running session's
own `maya.cmds` (see core/cmd.py's closing loop), so it works unmodified
against whatever Maya version happens to be running -- no vendoring/version
matching required on our side.

Usage: `import pymeltm.core as pm` wherever code used to `import pymel.core as pm`.
"""
