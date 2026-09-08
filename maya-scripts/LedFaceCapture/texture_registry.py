"""In-memory registry mapping a name to the live MTexture used by ledFaceMaterial nodes.

Nothing here ever touches disk: capture pixels flow render target -> RAM bytes
-> MTexture, updated in place frame to frame wherever possible (see
push_frame()). There is no `file` node and no image asset anywhere in this
pipeline.
"""
from __future__ import annotations

import maya.api.OpenMayaRender as omr
import maya.cmds as cmds

from . import _debug

_LED_FACE_MATERIAL_TYPE = "ledFaceMaterial"

# maya.api.OpenMayaRender has no standalone MRasterFormat class (confirmed
# absent from dir(omr), dir(MRenderTargetDescription), and the old-style
# maya.OpenMayaRender module) -- MRenderTargetDescription.setRasterFormat()/
# MTextureDescription.fFormat both just take a plain int, per
# help(omr.MRenderTargetDescription.setRasterFormat). The named constants
# turned out to live as flat attributes directly on MRenderer instead
# (confirmed via dir(omr.MRenderer): kR8G8B8A8_UNORM, kB8G8R8A8, etc. are all
# there) -- no guessing needed once you know to look there.
RASTER_FORMAT_R8G8B8A8_UNORM = omr.MRenderer.kR8G8B8A8_UNORM


class _Entry(object):
    __slots__ = ("texture", "width", "height")

    def __init__(self, texture, width, height):
        self.texture = texture
        self.width = width
        self.height = height


_ENTRIES = {}


def push_frame(name, width, height, rgba_bytes, row_pitch=None):
    """Upload a fresh RGBA8 frame for `name`, replacing whatever texture was there.

    rgba_bytes must be width*height*4 bytes (or row_pitch*height if the
    source buffer has row padding -- see MTexture.update()'s rowPitch
    parameter below). row_pitch defaults to tightly packed (width*4) when
    omitted.

    Reuses the existing GPU texture for `name` via MTexture.update() (an
    in-place upload onto the SAME GPU resource) whenever one already exists
    at the same dimensions -- an earlier version of this module assumed
    "MTexture has no single documented in-place pixel-update entry point
    that is stable across Maya versions" and unconditionally released the
    old texture and acquired a brand new GPU resource every single pushed
    frame instead. That assumption was wrong: MTexture.update() is a real,
    documented entry point (maya/MTextureManager.h in the Maya devkit
    headers) -- confirmed present in the Maya 2026 SDK, not just guessed.
    Releasing + reallocating a GPU texture every frame during Play is
    measurably heavier than an in-place update, so this only falls back to
    the old allocate-a-new-texture behaviour when there's no existing
    texture yet, its size changed, or the in-place update raises (format
    mismatch, older Maya version without this entry point, etc.).
    """
    if not name:
        return

    texture_manager = omr.MRenderer.getTextureManager()
    if texture_manager is None:
        return

    if row_pitch is None:
        row_pitch = width * 4

    entry = _ENTRIES.get(name)
    if entry is not None and entry.texture is not None and entry.width == width and entry.height == height:
        try:
            entry.texture.update(rgba_bytes, False, row_pitch)
            _mark_consumers_dirty(name)
            return
        except Exception:
            _debug.log_exception(
                "texture_registry.push_frame -- in-place MTexture.update() failed, "
                "falling back to acquiring a new texture this frame"
            )

    desc = omr.MTextureDescription()
    desc.setToDefault2DTexture()
    desc.fWidth = width
    desc.fHeight = height
    desc.fFormat = RASTER_FORMAT_R8G8B8A8_UNORM

    # Passing "" as the name asks Maya not to cache/dedupe by name, since we
    # intentionally want a brand new resource every call.
    new_texture = texture_manager.acquireTexture("", desc, rgba_bytes)
    if new_texture is None:
        return

    if entry is not None and entry.texture is not None:
        texture_manager.releaseTexture(entry.texture)

    _ENTRIES[name] = _Entry(new_texture, width, height)
    _mark_consumers_dirty(name)


def _mark_consumers_dirty(name):
    """Nothing about pushing a new frame here touches Maya's own dependency
    graph, so VP2 has no reason to think ledFaceMaterial needs its
    updateDevice() called again -- confirmed on Maya 2026: updateDevice()
    fired exactly once, right when the override first activated (with no
    texture registered yet), and never again despite postSceneRender pushing
    fresh frames every redraw after that. cmds.dgdirty() on every
    ledFaceMaterial node using this texture name is the standard Maya way to
    say "something you depend on changed, re-evaluate" -- untested from
    inside a render callback (which may run off Maya's main thread, the same
    class of risk that ruled out MGlobal.displayError elsewhere in this
    package) so this is wrapped defensively; if it turns out to be unsafe
    here, the fix is to drive this from a main-thread idle callback instead
    of from postSceneRender directly.

    This runs once per pushed frame -- during Play, every frame. The
    previous implementation walked EVERY plugin node in the whole scene
    (`MItDependencyNodes(kPluginDependNode)` -- any plugin's nodes, not just
    ours) and issued one cmds.dgdirty() call per match; on a scene with
    other plugins' nodes in it (Arnold shaders, other rigs, ...) that's a
    lot of wasted Python-level type-name string comparisons every frame.
    cmds.ls(type=...) is natively type-indexed in C++ so it only ever
    touches ledFaceMaterial nodes, and matches get dirtied in one batched
    call instead of N separate command-engine round trips.
    """
    try:
        candidates = cmds.ls(type=_LED_FACE_MATERIAL_TYPE) or []
        matches = [node for node in candidates if cmds.getAttr(node + ".textureName") == name]
        if matches:
            cmds.dgdirty(matches)
    except Exception:
        _debug.log_exception("texture_registry._mark_consumers_dirty")


def get_texture(name):
    entry = _ENTRIES.get(name)
    return entry.texture if entry is not None else None


def clear():
    texture_manager = omr.MRenderer.getTextureManager()
    for entry in _ENTRIES.values():
        if texture_manager is not None and entry.texture is not None:
            texture_manager.releaseTexture(entry.texture)
    _ENTRIES.clear()
