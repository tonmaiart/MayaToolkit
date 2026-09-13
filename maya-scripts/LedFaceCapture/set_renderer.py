"""Standalone utility to flip a model panel's Renderer between "LED Face
Capture" and stock "Viewport 2.0" from a script, instead of using the
Renderer menu by hand.

Doesn't auto-run anything -- source it, then call whichever function you
want from the Script Editor:

    exec(open(r"C:/Tonmai/FileWorkspace/cache/plugins/MayaToolkit/maya-scripts/LedFaceCapture/set_renderer.py").read())
    use_led_face_capture()   # active panel -> LED Face Capture
    use_viewport2()          # active panel -> stock Viewport 2.0

Or import it as a module and call the same functions from your own script:

    import LedFaceCapture.set_renderer as led_renderer
    led_renderer.use_led_face_capture()
    led_renderer.use_viewport2()

Both functions default to whichever model panel currently has focus; pass
panel="modelPanel4" (or panel="all" for every model panel) to target
something else.
"""
from __future__ import annotations

import maya.cmds as cmds

PLUGIN_NAME = "led_face_capture"
OVERRIDE_NAME = "ledFaceCaptureOverride"


def _show_message(text):
    cmds.inViewMessage(amg=text, pos="topCenter", fade=True, fadeStayTime=1500)


def _resolve_panels(panel):
    """None/omitted -> the focused model panel (falls back to the first one
    that exists). "all" -> every model panel. Anything else -> that one
    panel name, as-is (letting cmds.modelEditor raise if it's not real).
    """
    model_panels = cmds.getPanel(type="modelPanel")
    if panel == "all":
        return model_panels
    if panel is None:
        focused = cmds.getPanel(withFocus=True)
        if focused in model_panels:
            return [focused]
        return model_panels[:1]
    return [panel]


def use_led_face_capture(panel=None):
    """Switch `panel` (see _resolve_panels()) to the LED Face Capture
    override, loading the plug-in first if it isn't already.
    """
    if not cmds.pluginInfo(PLUGIN_NAME, query=True, loaded=True):
        cmds.loadPlugin(PLUGIN_NAME)

    panels = _resolve_panels(panel)
    if not panels:
        print("LedFaceCapture: no model panel found.")
        return
    for p in panels:
        cmds.modelEditor(p, edit=True, rendererOverrideName=OVERRIDE_NAME)
        print("LedFaceCapture: {} -> LED Face Capture".format(p))
    _show_message("Viewport renderer: <hl>LED Face Capture</hl>")


def use_viewport2(panel=None):
    """Switch `panel` (see _resolve_panels()) back to stock Viewport 2.0.

    Just clears rendererOverrideName -- does NOT unload the plug-in, so
    ledFaceMaterial nodes/shading still display normally (they're a plain
    VP2 shading-node override, independent of LedFaceCaptureOverride); only
    the extra offscreen capture pass stops running.
    """
    panels = _resolve_panels(panel)
    if not panels:
        print("LedFaceCapture: no model panel found.")
        return
    for p in panels:
        cmds.modelEditor(p, edit=True, rendererOverrideName="")
        print("LedFaceCapture: {} -> Viewport 2.0".format(p))
    _show_message("Viewport renderer: <hl>Viewport 2.0</hl>")
