"""ledFaceMaterial: a utility node whose VP2 draw is supplied by a custom
shading *fragment* (via MPxSurfaceShadingNodeOverride), meant to feed its
`outColor` into a real, already-correctly-drawn surface shader (e.g. a
`lambert`) rather than replacing the whole material like the earlier
MPxShaderOverride attempt did.

Architecture change history: the first version of this file implemented
MPxShaderOverride directly (a from-scratch replacement shader for VP2). That
was abandoned after exhausting every discoverable fix (shaderInstance() was
missing, stock shader parameter binding all confirmed working via
diagnostics) with the render item still refusing to draw anything -- not
even a hardcoded solid color -- while a plain `lambert` on the same mesh
rendered correctly. MPxSurfaceShadingNodeOverride only has to supply ONE
utility node's contribution to an already-working shading network (the
lambert's own technique handles the rest), which is a much smaller surface
to get wrong.

Usage in-scene (note the new wiring -- through a real lambert, not straight
to the shading engine):
    cmds.shadingNode("ledFaceMaterial", asUtility=True, name="robotFaceLED")
    cmds.setAttr("robotFaceLED.textureName", "<same string as the config node's textureName>", type="string")
    lam = cmds.shadingNode("lambert", asShader=True, name="robotFaceLED_lambert")
    cmds.connectAttr("robotFaceLED.outColor", lam + ".color")
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="robotFaceLEDSG")
    cmds.connectAttr(lam + ".outColor", sg + ".surfaceShader")
    cmds.sets("robotHeadFaceMesh", edit=True, forceElement=sg)

Phase 1 (confirmed working end to end on Maya 2026): a hardcoded-solid-red
fragment, ignoring `textureName`/the capture texture entirely, proved that
MPxShadingNodeOverride + a from-scratch fragment can draw *anything* at all
through a real lambert, under both stock Viewport 2.0 and LedFaceCaptureOverride.
Root cause of every prior "no error anywhere, still black" symptom (across
all three abandoned architectures) turned out to be a **type mismatch**: the
fragment's `<outputs>` declared a `float4`, but `ledFaceMaterial.outColor` is
a 3-component color attribute (`MFnNumericAttribute.createColor()`) -- Maya
silently refuses to splice a mismatched-arity fragment output into the
shading effect, the same "no error, just doesn't connect" failure mode as
the outputForConnection() name-mismatch case. Fixed by declaring `float3`
outputs/return types throughout. Also fixed in the same pass:
`NODE_CLASSIFICATION`'s Hypershade category was `:utility/general` (copied
from `multiplyDivide`/`condition`, which are math/sampling utilities), but
node that actually produce a color fed into another shader's color input --
`blendColors`/`clamp`/`remapColor`/`gammaCorrect` -- are all `:utility/color`
instead; changed to match.

Phase 2 (current): reintroducing texture sampling. The fragment now takes a
`map`/`mapSampler` texture property plus a `uvCoord` input (matched to the
mesh's UV set via the `mayaUvCoordSemantic` semantic) and samples it instead
of returning a hardcoded color. `updateDG()` caches the node's `textureName`
attribute (DG access is only safe there, never in updateShader()/render
callbacks); `updateShader()` looks up the live capture texture from
`texture_registry` by that name and binds it onto the fragment's `map`
parameter via `MTextureAssignment`. Unverified on first write, same as every
other API surface in this file -- expect to iterate against whatever Maya
reports.
"""
from __future__ import annotations

import maya.api.OpenMaya as om2
import maya.api.OpenMayaRender as omr

from . import _debug
from . import texture_registry

NODE_NAME = "ledFaceMaterial"
# TODO: placeholder from the devkit example range, replace with a
# studio-issued id before shipping.
NODE_ID = om2.MTypeId(0x0011D701)
# "operation" (a utility node contributing a value into a larger shading
# network), not "surface" (a standalone, complete surface shader) -- matches
# how Maya's own utility nodes are classified for VP2 draw registration.
# The ":utility/general" suffix (originally copied from
# cmds.getClassification("multiplyDivide") / ("condition")) was WRONG --
# confirmed by comparing against nodes that actually produce a COLOR fed
# straight into another shader's color input, the same role ledFaceMaterial
# plays here: cmds.getClassification("blendColors")/("clamp")/("remapColor")/
# ("gammaCorrect") all come back ":utility/color", not ":utility/general".
# multiplyDivide/condition/samplerInfo are general math/sampling utilities,
# not color producers, and ":utility/general" is their category, not ours --
# this mismatch is the most likely reason Maya's shading-graph builder never
# actually spliced our fragment into the final effect even though
# outputForConnection() reported a correct, matching connection every time.
DRAW_REGISTRY_KEY = "drawdb/shader/operation/ledFaceMaterial"
# registerNode's classification param wants the FULL combined string
# (drawdb path + Hypershade category); MDrawRegistry's registration calls
# want just the "drawdb/..." key on its own -- keeping these as two
# constants instead of splitting DRAW_REGISTRY_KEY out of one combined
# string at every call site.
NODE_CLASSIFICATION = DRAW_REGISTRY_KEY + ":utility/color"
DRAW_REGISTRANT_ID = "ledFaceMaterialRegistrant"


# Bumped from Tex5 -- Maya's MFragmentManager caches fragments by name for
# the life of the process (confirmed live: hasFragment() kept returning True
# and addShadeFragmentFromBuffer() was skipped even after this file's source
# changed, so a Maya session still running from before the scaleU/scaleV
# removal kept executing the OLD cached fragment code no matter how the
# .py was edited). A new name forces a genuinely fresh registration instead
# of silently testing stale GPU-side code -- bump this again any time the
# fragment source changes and a running Maya session needs to pick it up.
#
# This is now a PREFIX, not the fragment's actual name -- confirmed live:
# two ledFaceMaterial nodes both feeding a shared downstream node (e.g.
# summed via plusMinusAverage) only had ONE of the two textures actually
# show up, no matter which node/slot -- each node worked perfectly on its
# own, feeding a lambert directly, so the capture/texture_registry/shading
# chain per node was never the problem. Root cause: every ledFaceMaterial
# instance returned the exact same FRAGMENT_NAME from fragmentName()/
# outputForConnection(), so once two instances' output landed in the same
# compiled VP2 shading effect, Maya's compiler treated them as the SAME
# fragment usage site sharing ONE parameter binding (map/mapSampler) --
# whichever instance's updateShader() bound last simply overwrote the
# other's texture, so only one ever actually displayed. Each
# LedFaceShadingNodeOverride instance now registers and uses its OWN
# uniquely-named fragment (see __init__) built from this prefix, so
# multiple ledFaceMaterial nodes combined in one shading network no longer
# collide.
FRAGMENT_NAME_PREFIX = "ledFaceCaptureFragmentTex6"

# Phase 2: samples a real 2D texture (bound at render time from
# texture_registry, see updateDG()/updateShader() below) instead of the
# phase-1 hardcoded color. `map`/`mapSampler` are plain "texture2"/"sampler"
# properties -- MShaderInstance.setParameter() binds an MTextureAssignment/
# MSamplerState onto them by these exact names. `uvCoord` uses the
# "mayaUvCoordSemantic" semantic so Maya auto-feeds it from the mesh's
# current UV set with no explicit wiring needed, the same mechanism Maya's
# own file-texture fragments use. Output stays `float3` (see module
# docstring -- a float4 here was the phase-1 root cause). Unverified on
# first write: the exact per-language sampling syntax below (Texture2D+
# sampler split for HLSL vs combined sampler2D for Cg/GLSL) is reconstructed
# from general HLSL/GLSL/Cg conventions, not dumped from a live Maya
# fragment -- expect to iterate against whatever Maya reports on first load.
# Confirmed once the capture pass itself worked (non-zero lit pixels): the
# preview plane showed the rig mirrored left-right. For an orthographic
# camera aimed down -Z with up=+Y, "camera right" (the direction increasing
# column index in the rendered image) is world -X, not +X (cross(up,
# forward) with forward=(0,0,-1) works out to (-1,0,0)) -- so a texture
# column sampled directly by the mesh's own +X-increasing U coordinate reads
# the image backwards. Flipping the sampled U (`1.0 - uvCoord.x`) in every
# language implementation below corrects it without touching the mesh's UVs
# or the capture camera's orientation. Confirmed X-flip fix working; still
# needed the same treatment on V: the render target's raw scanline order (row
# 0 = the FIRST row Maya's rasterizer wrote, i.e. the top of the rendered
# image) doesn't match Maya's own UV convention (v=0 at the bottom of the
# mesh), so the untouched V coordinate read the buffer upside down. Flipping
# `uvCoord.y` the same way fixes it.
#
# Phase 2.1 (removed): a manual scaleU/scaleV fragment property used to let
# users correct capture-side aspect distortion by eye, because the actual
# root cause (render_override.py's capture camera aspect being derived from
# the destination viewport panel instead of the capture target's own pixel
# dimensions) hadn't been found yet. Now that cameraOverride() sets an
# explicit orthographic projection matrix instead, the capture itself comes
# out undistorted and this manual per-material fudge factor is no longer
# needed.
def _fragment_xml(name, impl_name):
    # `name` is this instance's unique fragment name (also doubles as its
    # single output parameter's name, matching Maya's convention); `impl_name`
    # is the internal shader FUNCTION name inside the HLSL/Cg/GLSL source
    # below. Both must be unique per ledFaceMaterial node instance, not just
    # `name` -- when two instances' fragments get merged into one compiled
    # VP2 shading effect (e.g. two ledFaceMaterial nodes summed together via
    # plusMinusAverage), Maya concatenates every fragment's source into one
    # shader program; two fragments both defining a function literally named
    # `ledFaceCaptureFragmentImpl` would collide there too, on top of the
    # fragment-name collision this was written to fix.
    return """<fragment uiName="{name}" name="{name}" type="plumbing" class="ShadeFragment" version="1.0" feature_level="20">
  <description><![CDATA[Samples the live LED capture texture for ledFaceMaterial (phase 2).]]></description>
  <keyword value="plumbing" />
  <properties>
    <float2 name="uvCoord" semantic="mayaUvCoordSemantic" flags="varyingInputParam" />
    <texture2 name="map" />
    <sampler name="mapSampler" />
  </properties>
  <outputs>
    <float3 name="{name}" />
  </outputs>
  <implementation>
    <implementation render="OGSRenderer" language="HLSL" lang_version="11.0">
      <function_name val="{impl_name}" />
      <source>
        <![CDATA[
float3 {impl_name}(float2 uvCoord, Texture2D map, sampler mapSampler)
{{
    float2 flipped = float2(uvCoord.x, 1.0 - uvCoord.y);
    return map.Sample(mapSampler, flipped).rgb;
}}
]]>
      </source>
    </implementation>
    <implementation render="OGSRenderer" language="Cg" lang_version="2.1">
      <function_name val="{impl_name}" />
      <source>
        <![CDATA[
float3 {impl_name}(float2 uvCoord, sampler2D map)
{{
    float2 flipped = float2(uvCoord.x, 1.0 - uvCoord.y);
    return tex2D(map, flipped).rgb;
}}
]]>
      </source>
    </implementation>
    <implementation render="OGSRenderer" language="GLSL" lang_version="3.0">
      <function_name val="{impl_name}" />
      <source>
        <![CDATA[
vec3 {impl_name}(vec2 uvCoord, sampler2D map)
{{
    vec2 flipped = vec2(uvCoord.x, 1.0 - uvCoord.y);
    return texture(map, flipped).rgb;
}}
]]>
      </source>
    </implementation>
  </implementation>
</fragment>""".format(name=name, impl_name=impl_name)


def _ensure_fragment_registered(name):
    try:
        frag_mgr = omr.MRenderer.getFragmentManager()
        _debug.log("LedFaceCapture: getFragmentManager() ->", frag_mgr)
        if frag_mgr is None:
            print("LedFaceCapture: no fragment manager -- fragment NEVER registered")
            return False
        already_has_it = frag_mgr.hasFragment(name)
        _debug.log("LedFaceCapture: hasFragment(%r) -> %r" % (name, already_has_it))
        if already_has_it:
            # Per-instance names are unique per Python-process-lifetime id()
            # (see LedFaceShadingNodeOverride.__init__) -- a name collision
            # here would only happen if id() got reused, which CPython does
            # do once an old object is garbage collected. Treat it the same
            # as the old shared-fragment code did: assume it's already the
            # right content and move on, rather than risk stepping on a
            # fragment another live instance still depends on.
            return True
        fragment_xml = _fragment_xml(name, name + "Impl")
        registered_name = frag_mgr.addShadeFragmentFromBuffer(fragment_xml.encode("utf-8"), False)
        _debug.log("LedFaceCapture: fragment registration returned", repr(registered_name))
        return bool(registered_name)
    except Exception:
        _debug.log_exception("_ensure_fragment_registered")
        return False


class LedFaceMaterial(om2.MPxNode):
    id = NODE_ID

    textureName = None
    outColor = None
    cameraMsg = None
    captureSetMsg = None
    resolutionX = None
    resolutionY = None
    atlasSources = None

    @staticmethod
    def creator():
        return LedFaceMaterial()

    @staticmethod
    def initialize():
        str_fn = om2.MFnTypedAttribute()
        num_fn = om2.MFnNumericAttribute()

        default_string = om2.MFnStringData().create("")
        LedFaceMaterial.textureName = str_fn.create(
            "textureName", "texName", om2.MFnData.kString, default_string
        )
        str_fn.storable = True
        str_fn.keyable = False
        om2.MPxNode.addAttribute(LedFaceMaterial.textureName)

        LedFaceMaterial.outColor = num_fn.createColor("outColor", "oc")
        num_fn.storable = False
        num_fn.writable = False
        om2.MPxNode.addAttribute(LedFaceMaterial.outColor)

        # Formerly the separate ledCaptureConfig node type (cameraName,
        # captureSetName, resolutionX/Y) -- folded directly onto
        # ledFaceMaterial so one node fully self-describes both "how to
        # capture" and "how to display" a texture channel, and the render
        # override can drive an arbitrary number of independent capture
        # passes (one per distinct textureName found on any ledFaceMaterial
        # in the scene) instead of only ever the single ledCaptureConfig
        # node it used to look for.
        #
        # cameraName/captureSetName (plain string attrs) were removed: a
        # string doesn't survive `file -reference` -- the referenced
        # camera/set gets a namespace prefix (or collides with another
        # reference's copy) and the string still holds the old
        # un-namespaced text, so render_override.py's MSelectionList.add()
        # lookup started failing or resolving to the wrong node. These
        # message attributes replace them: connect the camera/set's
        # `.message` here (`cmds.connectAttr(cam + ".message", node + ".cameraMsg")`,
        # same for captureSetMsg) instead. A real DG connection has none of
        # the string's problem -- Maya rewrites/remaps connections through
        # reference namespaces automatically, the same mechanism every other
        # node-to-node wire in the scene already relies on.
        msg_fn = om2.MFnMessageAttribute()
        LedFaceMaterial.cameraMsg = msg_fn.create("cameraMsg", "camMsg")
        om2.MPxNode.addAttribute(LedFaceMaterial.cameraMsg)

        msg_fn = om2.MFnMessageAttribute()
        LedFaceMaterial.captureSetMsg = msg_fn.create("captureSetMsg", "capSetMsg")
        om2.MPxNode.addAttribute(LedFaceMaterial.captureSetMsg)

        num_fn = om2.MFnNumericAttribute()
        LedFaceMaterial.resolutionX = num_fn.create(
            "resolutionX", "resX", om2.MFnNumericData.kInt, 64
        )
        num_fn.storable = True
        om2.MPxNode.addAttribute(LedFaceMaterial.resolutionX)

        num_fn = om2.MFnNumericAttribute()
        LedFaceMaterial.resolutionY = num_fn.create(
            "resolutionY", "resY", om2.MFnNumericData.kInt, 64
        )
        num_fn.storable = True
        om2.MPxNode.addAttribute(LedFaceMaterial.resolutionY)

        # Comma-separated texture_registry channel names (e.g. "L,R") to
        # assemble side-by-side into THIS node's own textureName every
        # frame -- see texture_registry.compose_horizontal_atlas() and
        # render_override.py's setup(). Leave blank on a node that's meant
        # to be its own capture source (the normal case); set it only on a
        # dedicated "combined display" node that isn't a capture source
        # itself (cameraName/captureSetName left blank on that one --
        # render_override.py skips capture-config discovery for any node
        # with atlasSources set, see _find_capture_configs()).
        str_fn = om2.MFnTypedAttribute()
        LedFaceMaterial.atlasSources = str_fn.create(
            "atlasSources", "atlasSrc", om2.MFnData.kString, default_string
        )
        str_fn.storable = True
        str_fn.keyable = False
        om2.MPxNode.addAttribute(LedFaceMaterial.atlasSources)


class LedFaceShadingNodeOverride(omr.MPxShadingNodeOverride):
    """Phase 2: supplies the texture-sampling fragment for ledFaceMaterial's
    VP2 draw and binds the live texture_registry entry onto it every frame
    via updateDG()/updateShader(). Phase 1 (hardcoded red, no
    texture_registry involvement) confirmed the mechanism draws anything at
    all end to end -- see the module docstring for the float3/float4 type
    mismatch that was the real root cause of that phase's "still black"
    symptom.

    Base class fixed from MPxSurfaceShadingNodeOverride to plain
    MPxShadingNodeOverride: per Autodesk's own docs (Shading Node Overrides
    devhelp page), MPxSurfaceShadingNodeOverride is specifically for a node
    "connected directly to a Maya shading engine" -- i.e. a complete,
    standalone surface shader, which is exactly the design this file moved
    away from. ledFaceMaterial is a utility node feeding one input
    (lambert.color) on another shader, which is what the plain
    MPxShadingNodeOverride + MDrawRegistry.registerShadingNodeOverrideCreator
    pairing is for (confirmed as a genuinely separate registration function
    from registerSurfaceShadingNodeOverrideCreator via dir(MDrawRegistry)).
    The Surface subclass's extra methods (primaryColorParameter,
    transparencyParameter, bumpAttribute) don't exist on this base at all --
    confirmed via dir(MPxShadingNodeOverride) -- so this was never going to
    connect correctly no matter how outputForConnection/the fragment XML
    were fixed.
    """

    @staticmethod
    def creator(obj):
        return LedFaceShadingNodeOverride(obj)

    def __init__(self, obj):
        omr.MPxShadingNodeOverride.__init__(self, obj)
        self._node_obj = obj
        self._texture_name = ""
        self._sampler_state = None
        # Unique per instance -- see FRAGMENT_NAME_PREFIX's docstring for why
        # sharing one fragment name across every ledFaceMaterial node was the
        # actual bug behind "two of these combined in one shading network,
        # only one ever displays". Same id()-based uniqueness trick already
        # used for render_override.py's per-capture-channel render target
        # names. Registered immediately (not lazily in fragmentName()) so a
        # fresh fragment exists in the FragmentManager before Maya's shading
        # compiler can ever ask for it.
        self._fragment_name = "{}_{:08x}".format(FRAGMENT_NAME_PREFIX, id(self) & 0xFFFFFFFF)
        _ensure_fragment_registered(self._fragment_name)

    def supportedDrawAPIs(self):
        # Never overridden before this point in the prototype's history --
        # help(MPxShadingNodeOverride.supportedDrawAPIs) gives no "default
        # implementation returns ..." line (every other method here that has
        # a safe default says so explicitly), which is the same shape of gap
        # that hid the shaderInstance() bug in the abandoned MPxShaderOverride
        # path. If the un-overridden default reports "no APIs supported",
        # this override would never be used to draw at all regardless of how
        # correct the fragment/wiring is -- kAllDevices rules that out.
        apis = omr.MRenderer.kAllDevices
        _debug.log("LedFaceCapture: supportedDrawAPIs() called, returning", apis)
        return apis

    def fragmentName(self):
        _debug.log("LedFaceCapture: LedFaceShadingNodeOverride.fragmentName() called")
        return self._fragment_name

    def outputForConnection(self, source_plug, destination_plug):
        # Default implementation returns the name of our node's own output
        # ATTRIBUTE ("outColor"), not the fragment's output PARAMETER name --
        # confirmed via help() that a mismatch here means "the fragment will
        # not be connected to the overall shading effect" at all, which
        # produces exactly a solid-black render item with no error anywhere.
        if _debug.DEBUG_ENABLED:
            try:
                source_name = source_plug.name()
            except Exception:
                source_name = repr(source_plug)
            try:
                dest_name = destination_plug.name()
            except Exception:
                dest_name = repr(destination_plug)
            _debug.log(
                "LedFaceCapture: outputForConnection() called, source=%s dest=%s -> returning %r"
                % (source_name, dest_name, self._fragment_name)
            )
        return self._fragment_name

    def updateDG(self):
        # Real signature confirmed via help(omr.MPxShadingNodeOverride) --
        # "updateDG() -> self", no obj parameter at all (unlike
        # MPxShaderOverride.updateDG(obj), a different base class this file
        # used before -- confirmed the hard way: Maya raised "missing 1
        # required positional argument: 'obj'" against the first draft here).
        # The node's MObject only ever arrives via creator(obj)/__init__(obj),
        # cached as self._node_obj there -- reuse it instead.
        # Only safe place to touch the dependency graph -- updateShader() is
        # documented as an error to access the DG from (render-thread-adjacent,
        # like every other callback in this package flagged with the same
        # caveat). Cache textureName here; look up the actual texture in
        # updateShader() instead.
        try:
            node_fn = om2.MFnDependencyNode(self._node_obj)
            self._texture_name = node_fn.findPlug("textureName", False).asString()
        except Exception:
            _debug.log_exception("LedFaceShadingNodeOverride.updateDG")
            self._texture_name = ""

    def updateShader(self, shader, mappings):
        try:
            texture = texture_registry.get_texture(self._texture_name)
            _debug.log(
                "LedFaceCapture: updateShader() textureName=%r -> texture=%r"
                % (self._texture_name, texture)
            )
            if texture is None:
                return
            texture_assignment = omr.MTextureAssignment()
            texture_assignment.texture = texture
            shader.setParameter("map", texture_assignment)

            if self._sampler_state is None:
                desc = omr.MSamplerStateDesc()
                desc.filter = omr.MSamplerState.kMinMagMipLinear
                desc.addressU = omr.MSamplerState.kTexClamp
                desc.addressV = omr.MSamplerState.kTexClamp
                self._sampler_state = omr.MStateManager.acquireSamplerState(desc)
                print("LedFaceCapture: acquired sampler state ->", self._sampler_state)
            if self._sampler_state is not None:
                shader.setParameter("mapSampler", self._sampler_state)
        except Exception:
            _debug.log_exception("LedFaceShadingNodeOverride.updateShader")


def register(plugin_fn):
    print("LedFaceCapture: node_led_face_material.register() running, classification =", NODE_CLASSIFICATION)
    plugin_fn.registerNode(
        NODE_NAME,
        LedFaceMaterial.id,
        LedFaceMaterial.creator,
        LedFaceMaterial.initialize,
        om2.MPxNode.kDependNode,
        NODE_CLASSIFICATION,
    )
    # No module-level fragment registration any more -- each
    # LedFaceShadingNodeOverride instance registers its own uniquely-named
    # fragment in its __init__ instead (see FRAGMENT_NAME_PREFIX's docstring).
    omr.MDrawRegistry.registerShadingNodeOverrideCreator(
        DRAW_REGISTRY_KEY, DRAW_REGISTRANT_ID, LedFaceShadingNodeOverride.creator
    )
    print("LedFaceCapture: registerShadingNodeOverrideCreator done for", DRAW_REGISTRY_KEY)


def deregister(plugin_fn):
    omr.MDrawRegistry.deregisterShadingNodeOverrideCreator(DRAW_REGISTRY_KEY, DRAW_REGISTRANT_ID)
    plugin_fn.deregisterNode(LedFaceMaterial.id)
