"""Minimal, capture-free isolation test: does ledFaceMaterial's VP2 fragment
draw ANY color at all, under stock Viewport 2.0 (not LedFaceCaptureOverride)?

No camera, no render target, no texture_registry, no LedFaceCaptureOverride
involvement whatsoever -- just node -> lambert -> shading engine -> plane,
viewed under Maya's own standard renderer. Isolates the shading-node-override
/ fragment mechanism from every other moving part in this prototype.

Run directly (Script Editor > File > Source Script..., or):
    exec(open(r"C:/Tonmai/FileWorkspace/cache/plugins/MayaToolkit/maya-scripts/LedFaceCapture/dev_minimal_color_test.py").read())
"""
from __future__ import annotations

import maya.cmds as cmds

PLUGIN_NAME = "led_face_capture"
OVERRIDE_NAME = "ledFaceCaptureOverride"


def run():
    # Make sure no panel is still pointed at our custom override -- we want
    # stock Viewport 2.0 for this test, full stop.
    for panel in cmds.getPanel(type="modelPanel"):
        if cmds.modelEditor(panel, query=True, rendererOverrideName=True) == OVERRIDE_NAME:
            cmds.modelEditor(panel, edit=True, rendererOverrideName="")

    if cmds.pluginInfo(PLUGIN_NAME, query=True, loaded=True):
        cmds.unloadPlugin(PLUGIN_NAME)
    cmds.loadPlugin(PLUGIN_NAME)

    import LedFaceCapture
    print("LedFaceCapture build:", LedFaceCapture.version())

    mat = cmds.shadingNode("ledFaceMaterial", asUtility=True, name="colorTest_mat")
    lam = cmds.shadingNode("lambert", asShader=True, name="colorTest_lambert")
    cmds.connectAttr(mat + ".outColor", lam + ".color", force=True)

    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="colorTest_lambertSG")
    cmds.connectAttr(lam + ".outColor", sg + ".surfaceShader", force=True)

    plane, _ = cmds.polyPlane(name="colorTest_plane", width=4, height=4, subdivisionsX=1, subdivisionsY=1)
    cmds.setAttr(plane + ".rotateX", 90)
    cmds.sets(plane, edit=True, forceElement=sg)

    cmds.select(plane)
    cmds.viewFit()
    cmds.select(clear=True)

    target_panel = cmds.getPanel(withFocus=True)
    model_panels = cmds.getPanel(type="modelPanel")
    if target_panel not in model_panels:
        target_panel = model_panels[0] if model_panels else None

    if target_panel:
        # Explicitly stock VP2, hardware texturing on, so this is as close
        # to Maya's own default "does this material show up" test as
        # possible -- no custom override anywhere in the picture.
        cmds.modelEditor(target_panel, edit=True, rendererOverrideName="", displayTextures=True)
        cmds.refresh(force=True)
        print(
            "LedFaceCapture: minimal color test ready on", target_panel,
            "-- plane:", plane, "material:", mat,
            "(stock Viewport 2.0, no LedFaceCaptureOverride)",
        )
        print("LedFaceCapture: check the plane's color now -- expect solid red if the fragment mechanism works at all.")
    else:
        print("LedFaceCapture: no model panel found.")


run()
