"""Aspect-correctness regression test for the cameraOverride() fix in
render_override.py (explicit orthographic projection matrix, replacing the
old scaleU/scaleV manual-correction workaround on ledFaceMaterial).

Builds the usual square 4x4 rig, lights a corner-to-corner diagonal pattern
(same as dev_smoke_test.py) so the lit-pixel bounding box spans the full
square world extent in both axes, then forces a capture at a few different
config resolutions -- including a deliberately NON-square one -- to confirm
the fix holds regardless of the capture target's own pixel dimensions, not
just the default square 64x64 case.

Nothing here reads the result programmatically: every measurement Maya's own
render callbacks produce only goes to stdout (see _debug.py's docstring for
why -- render-thread-adjacent code can't safely call back into Maya's UI/
command layer). Run this, then read the Script Editor output for lines like:

    LedFaceCapture: postSceneRender -- lit-pixel bbox width=.../... (...) height=.../... (...) -- fractional ratio=X.XXX (1.0 means no distortion)

One such line prints per forced refresh, in the same order as the
RESOLUTIONS_TO_TEST list below. fractional ratio should read ~1.000 (say,
within +/-0.02 for pixel-rounding) at every resolution -- if any of them
drift noticeably from 1.0, the cameraOverride() projection-matrix fix has
regressed.

Run directly (Script Editor > File > Source Script..., or):
    exec(open(r"C:/Tonmai/FileWorkspace/cache/plugins/MayaToolkit/maya-scripts/LedFaceCapture/dev_aspect_tune_test.py").read())
"""
from __future__ import annotations

import maya.cmds as cmds

PLUGIN_NAME = "led_face_capture"
OVERRIDE_NAME = "ledFaceCaptureOverride"

# Square first (the historically broken case), then two non-square targets
# -- one wider-than-tall, one taller-than-wide -- to prove the fix isn't
# accidentally tied to the default square resolution.
RESOLUTIONS_TO_TEST = [
    (64, 64),
    (96, 48),
    (48, 96),
]


def _clear_override_everywhere():
    for panel in cmds.getPanel(type="modelPanel"):
        if cmds.modelEditor(panel, query=True, rendererOverrideName=True) == OVERRIDE_NAME:
            cmds.modelEditor(panel, edit=True, rendererOverrideName="")


def run():
    _clear_override_everywhere()

    if cmds.pluginInfo(PLUGIN_NAME, query=True, loaded=True):
        cmds.unloadPlugin(PLUGIN_NAME)
    cmds.loadPlugin(PLUGIN_NAME)

    import LedFaceCapture
    print("LedFaceCapture build:", LedFaceCapture.version())

    import LedFaceCapture.test_scene_setup as led_test
    if cmds.objExists(led_test._name("config")):
        led_test.cleanup()
    built = led_test.build()
    config = built["config"]

    # Corner-to-corner diagonal -- spans the full square bbox in both X and
    # Y, same pattern dev_smoke_test.py uses, so a distorted capture shows up
    # as bbox_w != bbox_h (or, for non-square targets, frac_w != frac_h) in
    # the postSceneRender() diagnostic.
    led_test.set_pattern([(0, 0), (1, 1), (2, 2), (3, 3)])

    cmds.select(cmds.ls("ledTest_*"))
    cmds.viewFit()
    cmds.select(clear=True)

    target_panel = cmds.getPanel(withFocus=True)
    model_panels = cmds.getPanel(type="modelPanel")
    if target_panel not in model_panels:
        target_panel = model_panels[0] if model_panels else None

    if not target_panel:
        print("LedFaceCapture: no model panel found -- enable Renderer > LED Face Capture manually.")
        return

    cmds.modelEditor(target_panel, edit=True, rendererOverrideName=OVERRIDE_NAME, displayTextures=True)

    for width, height in RESOLUTIONS_TO_TEST:
        cmds.setAttr(config + ".resolutionX", width)
        cmds.setAttr(config + ".resolutionY", height)
        print("LedFaceCapture: ---- testing capture resolution {}x{} ----".format(width, height))
        cmds.refresh(force=True)

    print(
        "LedFaceCapture: aspect tune test done -- scroll up and check each "
        "'fractional ratio=' line against the resolution printed just above "
        "it. All should read ~1.000. led_test.cleanup() to remove the rig "
        "when finished."
    )


run()
