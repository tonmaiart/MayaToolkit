"""One-shot smoke test for LedFaceCapture. Assumes YOU already did File > New
(this script does not touch the scene for you, on purpose -- run it right
after starting a fresh scene yourself). It then (re)loads the plug-in the
safe way (no force-unload -- that's what corrupted node-type registration
earlier in this prototype's history), builds the test rig, applies a
pattern, frames the viewport on it, and switches one panel to the LED Face
Capture override with textures on.

Run directly as a file (Maya Script Editor > File > Source Script..., or):

    exec(open(r"C:/Tonmai/FileWorkspace/cache/plugins/MayaToolkit/maya-scripts/LedFaceCapture/dev_smoke_test.py").read())
"""
from __future__ import annotations

import maya.cmds as cmds

PLUGIN_NAME = "led_face_capture"
OVERRIDE_NAME = "ledFaceCaptureOverride"

# Set False to isolate whether a bug is specifically tied to textured
# display turning on (vs. the override/geometry pipeline in general).
# Reads a pre-set global if you define one before exec()-ing this file, e.g.:
#   ENABLE_TEXTURES = False
#   exec(open(r"...dev_smoke_test.py").read())
# so you don't have to hand-edit this file to flip it.
ENABLE_TEXTURES = globals().get("ENABLE_TEXTURES", True)


def clear_override_everywhere():
    """rendererOverrideName is per-panel UI state, not scene state -- File >
    New does NOT reset it. A panel left pointed at our override from a
    previous run is exactly what makes unloadPlugin say "still in use" even
    right after starting a fresh scene.
    """
    for panel in cmds.getPanel(type="modelPanel"):
        if cmds.modelEditor(panel, query=True, rendererOverrideName=True) == OVERRIDE_NAME:
            cmds.modelEditor(panel, edit=True, rendererOverrideName="")


def run():
    clear_override_everywhere()

    # 1. Reload the plug-in the safe way. No force=True: if this ever
    #    complains "still in use" here on a scene you just started fresh,
    #    something is wrong -- stop and look, don't force past it, that's
    #    what corrupted node-type registration earlier.
    if cmds.pluginInfo(PLUGIN_NAME, query=True, loaded=True):
        cmds.unloadPlugin(PLUGIN_NAME)
    cmds.loadPlugin(PLUGIN_NAME)

    import LedFaceCapture
    print("LedFaceCapture build:", LedFaceCapture.version())

    # 2. Build the test rig and apply a pattern.
    import LedFaceCapture.test_scene_setup as led_test
    led_test.build()
    led_test.set_pattern([(0, 0), (1, 1), (2, 2), (3, 3)])

    # 3. Frame the viewport on everything we just created.
    cmds.select(cmds.ls("ledTest_*"))
    cmds.viewFit()
    cmds.select(clear=True)

    # 4. Point a model panel at the override and turn textures on.
    target_panel = cmds.getPanel(withFocus=True)
    model_panels = cmds.getPanel(type="modelPanel")
    if target_panel not in model_panels:
        target_panel = model_panels[0] if model_panels else None

    if target_panel:
        cmds.modelEditor(target_panel, edit=True, rendererOverrideName=OVERRIDE_NAME)
        if ENABLE_TEXTURES:
            cmds.modelEditor(target_panel, edit=True, displayTextures=True)
        print(
            "LedFaceCapture: override enabled on", target_panel,
            "(textures {})".format("ON" if ENABLE_TEXTURES else "OFF"),
        )
        # Setting rendererOverrideName does not itself force an immediate
        # paint -- Maya's setup()/renderTargets()/postSceneRender()/etc.
        # callbacks only actually fire on a real redraw. Force one now so
        # any print()/log_exception output from those callbacks shows up
        # right here instead of silently waiting for the next time the
        # viewport happens to repaint on its own.
        cmds.refresh(force=True)
        print("LedFaceCapture: forced a refresh -- check above for callback log lines")
    else:
        print("LedFaceCapture: no model panel found -- enable Renderer > LED Face Capture manually.")


run()
