"""In-memory registry mapping a name to the live MTexture used by ledFaceMaterial nodes.

Nothing here ever touches disk: capture pixels flow render target -> RAM bytes
-> MTexture, updated in place frame to frame wherever possible (see
push_frame()). There is no `file` node and no image asset anywhere in this
pipeline.
"""
from __future__ import annotations

import ctypes

import maya.api.OpenMayaRender as omr
import maya.cmds as cmds

from . import _debug

_LED_FACE_MATERIAL_TYPE = "ledFaceMaterial"
_LED_FACE_BLEND_TYPE = "ledFaceBlend"
# Must match node_led_face_blend.MAX_INPUTS -- duplicated here (rather than
# imported) to avoid a circular import (node_led_face_blend imports this
# module to call get_texture()/get_dummy_black()).
_LED_FACE_BLEND_MAX_INPUTS = 4

_DUMMY_BLACK_NAME = "__ledFaceCaptureDummyBlack__"
_dummy_black_texture = None

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

        # ledFaceBlend nodes (node_led_face_blend.py) sum several named
        # textures together -- any one of its N slots matching `name` means
        # this node's composited output needs to redraw too.
        for node in (cmds.ls(type=_LED_FACE_BLEND_TYPE) or []):
            for i in range(_LED_FACE_BLEND_MAX_INPUTS):
                if cmds.getAttr("%s.textureName%d" % (node, i)) == name:
                    matches.append(node)
                    break

        if matches:
            cmds.dgdirty(matches)
    except Exception:
        _debug.log_exception("texture_registry._mark_consumers_dirty")


def get_texture(name):
    entry = _ENTRIES.get(name)
    return entry.texture if entry is not None else None


def get_dummy_black():
    """A 1x1 fully-opaque black MTexture, lazily created once and cached for
    the life of the process.

    Used by node_led_face_blend.py to fill any of its input slots that
    don't have a real textureName set, so its fragment can always sample
    all N slots and sum them unconditionally (no per-slot branching in the
    shader for "is this one even bound") -- an unbound slot just
    contributes (0, 0, 0) to the sum, same as texture_registry not having
    an entry for it yet.
    """
    global _dummy_black_texture
    if _dummy_black_texture is not None:
        return _dummy_black_texture
    texture_manager = omr.MRenderer.getTextureManager()
    if texture_manager is None:
        return None
    desc = omr.MTextureDescription()
    desc.setToDefault2DTexture()
    desc.fWidth = 1
    desc.fHeight = 1
    desc.fFormat = RASTER_FORMAT_R8G8B8A8_UNORM
    _dummy_black_texture = texture_manager.acquireTexture(_DUMMY_BLACK_NAME, desc, b"\x00\x00\x00\xff")
    return _dummy_black_texture


def compose_horizontal_atlas(output_name, source_names):
    """Reads back the current pixels of each of `source_names` (in order)
    and concatenates them left-to-right into ONE combined RGBA8 buffer,
    then pushes that as `output_name` via push_frame().

    Exists so several independently-captured channels (e.g. one per eye)
    can share ONE final texture with zero risk of one's content bleeding
    into another's: they occupy strictly disjoint pixel COLUMNS by
    construction, decided here in plain Python, never by blending/summing
    pixel values together in a shader. That distinction matters for this
    plugin specifically -- every attempt at combining multiple
    ledFaceMaterial outputs via a shading-network node (layeredTexture,
    plusMinusAverage, a custom multi-texture blend fragment) ran into VP2
    fragment-splicing/compilation problems serious enough to abandon that
    whole approach; assembling the pixels directly here needs no fragment
    splicing of any kind.

    Sources of differing heights are top-aligned against the tallest one;
    the gap (if any) stays black. A source with no current entry (capture
    hasn't produced a frame yet) is skipped, leaving its column black too.
    """
    if not output_name or not source_names:
        return

    sources = []
    for name in source_names:
        entry = _ENTRIES.get(name)
        if entry is None or entry.texture is None:
            continue
        try:
            raw_ptr, row_pitch, slice_pitch = entry.texture.rawData()
            if not raw_ptr:
                continue
            raw_bytes = ctypes.string_at(raw_ptr, slice_pitch)
            entry.texture.freeRawData(raw_ptr)
        except Exception:
            _debug.log_exception("texture_registry.compose_horizontal_atlas -- reading %r" % name)
            continue
        sources.append((entry.width, entry.height, row_pitch, raw_bytes))

    if not sources:
        return

    total_width = sum(width for width, height, row_pitch, raw_bytes in sources)
    max_height = max(height for width, height, row_pitch, raw_bytes in sources)
    if total_width <= 0 or max_height <= 0:
        return

    # Zero-filled -- reads back as black in any gap/padding area. Alpha is
    # irrelevant either way: the ledFaceMaterial fragment only ever samples
    # `.rgb` (see node_led_face_material.py), never touches alpha.
    out_row_pitch = total_width * 4
    out_buffer = bytearray(out_row_pitch * max_height)

    x_offset = 0
    for width, height, row_pitch, raw_bytes in sources:
        row_bytes = width * 4
        for row in range(height):
            src_start = row * row_pitch
            dst_start = row * out_row_pitch + x_offset * 4
            out_buffer[dst_start:dst_start + row_bytes] = raw_bytes[src_start:src_start + row_bytes]
        x_offset += width

    push_frame(output_name, total_width, max_height, bytes(out_buffer), out_row_pitch)


def clear():
    texture_manager = omr.MRenderer.getTextureManager()
    for entry in _ENTRIES.values():
        if texture_manager is not None and entry.texture is not None:
            texture_manager.releaseTexture(entry.texture)
    _ENTRIES.clear()

    global _dummy_black_texture
    if texture_manager is not None and _dummy_black_texture is not None:
        texture_manager.releaseTexture(_dummy_black_texture)
    _dummy_black_texture = None
