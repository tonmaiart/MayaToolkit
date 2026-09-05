"""Diagnostic helper for LedFaceCapture's VP2 render-callback methods.

Maya's internal render loop catches exceptions raised inside MRenderOverride/
MSceneRender/MPxShaderOverride callback methods (cameraOverride,
objectSetOverride, renderTargets, postSceneRender, updateDG, updateDevice,
...) at a boundary that reports only str(exception) with no file/line -- very
different from a normal top-level script error. log_exception() prints the
real traceback so the console shows exactly which line and call actually
failed, instead of a bare, unattributable message repeating across totally
unrelated trigger actions.

Deliberately uses plain print(), not om2.MGlobal.displayError()/displayInfo():
these render callbacks can run off Maya's main thread, and MGlobal's UI/
command-layer calls are not guaranteed safe to call from there -- calling
them from the wrong thread can itself raise, which would silently swallow the
very exception this module exists to surface. print() writes straight to
stdout with no such dependency.
"""
from __future__ import annotations

import traceback


def log_exception(context):
    print("LedFaceCapture [{}]:\n{}".format(context, traceback.format_exc()))
