"""In-memory registry mapping a name to the live MTexture used by ledFaceMaterial nodes.

Nothing here ever touches disk: capture pixels flow render target -> RAM bytes
-> MTexture, and the same registry entry is rebound into the viewport shader
every refresh. There is no `file` node and no image asset anywhere in this
pipeline.
"""
from __future__ import annotations

import maya.api.OpenMayaRender as omr

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


def push_frame(name, width, height, rgba_bytes):
    """Upload a fresh RGBA8 frame for `name`, replacing whatever texture was there.

    rgba_bytes must be width*height*4 bytes, row-major, top row first.

    MTexture has no single documented in-place pixel-update entry point that
    is stable across Maya versions, so the safe approach used here is:
    acquire a brand new texture object from the raw buffer every frame and
    release the previous one. acquireTexture()'s raw-data overload builds the
    GPU resource directly from the bytes passed in -- no file, no disk round
    trip involved.
    """
    if not name:
        return

    texture_manager = omr.MRenderer.getTextureManager()
    if texture_manager is None:
        return

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

    old_entry = _ENTRIES.get(name)
    if old_entry is not None and old_entry.texture is not None:
        texture_manager.releaseTexture(old_entry.texture)

    _ENTRIES[name] = _Entry(new_texture, width, height)


def get_texture(name):
    entry = _ENTRIES.get(name)
    return entry.texture if entry is not None else None


def clear():
    texture_manager = omr.MRenderer.getTextureManager()
    for entry in _ENTRIES.values():
        if texture_manager is not None and entry.texture is not None:
            texture_manager.releaseTexture(entry.texture)
    _ENTRIES.clear()
