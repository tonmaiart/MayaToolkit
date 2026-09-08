"""ledFaceBlend: a utility node that ADDS together up to MAX_INPUTS separate
texture_registry channels (by name) into one combined outColor, entirely
inside its own VP2 fragment.

Why this exists instead of wiring several `ledFaceMaterial` nodes into a
native Maya math node (`plusMinusAverage`, `layeredTexture`): every attempt
at that failed, but only when TWO OR MORE `ledFaceMaterial` nodes fed the
SAME downstream node -- each one worked perfectly on its own, feeding a
lambert directly. Root cause (see node_led_face_material.py's
FRAGMENT_NAME_PREFIX docstring): every `ledFaceMaterial` instance used to
register/return the exact same VP2 fragment name, so once two instances'
outputs landed in one compiled shading effect together, Maya's compiler
conflated them into ONE shared fragment usage with ONE parameter binding --
only the last-bound texture actually showed. That's fixed now (each
ledFaceMaterial instance gets its own uniquely-named fragment), but chaining
N *separate* custom-fragment nodes into a *native* combiner still asks
Maya's shading-effect compiler to correctly splice N independent custom
fragments into one node's N input slots -- a scenario this prototype has
already been burned by once. This node sidesteps that whole class of
problem: there is only ONE fragment involved (this node's own), and it does
all N texture_registry lookups + the addition itself, internally, in one
shader. No inter-node custom-fragment splicing required for the "add" part
at all.

Usage:
    blend = cmds.shadingNode("ledFaceBlend", asUtility=True, name="ledFaceBlend1")
    cmds.setAttr(blend + ".textureName0", "L", type="string")
    cmds.setAttr(blend + ".textureName1", "R", type="string")
    # textureName2/textureName3 left blank if unused -- an unset slot just
    # contributes black (0,0,0) to the sum, see texture_registry.get_dummy_black().

    lam = cmds.shadingNode("lambert", asShader=True, name="ledFaceBlend1_lambert")
    cmds.connectAttr(blend + ".outColor", lam + ".color")
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="ledFaceBlend1SG")
    cmds.connectAttr(lam + ".outColor", sg + ".surfaceShader")
    cmds.sets("someMesh", edit=True, forceElement=sg)
"""
from __future__ import annotations

import maya.api.OpenMaya as om2
import maya.api.OpenMayaRender as omr

from . import _debug
from . import texture_registry

NODE_NAME = "ledFaceBlend"
# TODO: placeholder from the devkit example range, replace with a
# studio-issued id before shipping. Distinct from ledFaceMaterial's
# 0x0011D701 and the retired ledCaptureConfig's 0x0011D700.
NODE_ID = om2.MTypeId(0x0011D702)
DRAW_REGISTRY_KEY = "drawdb/shader/operation/ledFaceBlend"
NODE_CLASSIFICATION = DRAW_REGISTRY_KEY + ":utility/color"
DRAW_REGISTRANT_ID = "ledFaceBlendRegistrant"

# How many texture_registry channels one ledFaceBlend node can sum. A fixed,
# small number (not a growable array) on purpose -- VP2 fragments declare a
# static set of texture/sampler properties, they can't have a truly dynamic
# count. Bump this (and add matching map/mapSampler properties + sum terms
# in _fragment_xml(), plus textureNameN attributes in initialize()) if more
# than 4 channels are ever needed; keep texture_registry.py's
# _LED_FACE_BLEND_MAX_INPUTS in sync.
MAX_INPUTS = 4

# Same per-instance-uniqueness requirement as node_led_face_material.py's
# FRAGMENT_NAME_PREFIX -- see this file's module docstring for why.
FRAGMENT_NAME_PREFIX = "ledFaceBlendFragment1"


def _fragment_xml(name, impl_name):
    map_props = "\n    ".join(
        '<texture2 name="map{i}" />\n    <sampler name="mapSampler{i}" />'.format(i=i)
        for i in range(MAX_INPUTS)
    )
    hlsl_params = ", ".join("Texture2D map{i}, sampler mapSampler{i}".format(i=i) for i in range(MAX_INPUTS))
    cg_glsl_params = ", ".join("sampler2D map{i}".format(i=i) for i in range(MAX_INPUTS))
    hlsl_sum = " + ".join("map{i}.Sample(mapSampler{i}, flipped).rgb".format(i=i) for i in range(MAX_INPUTS))
    cg_sum = " + ".join("tex2D(map{i}, flipped).rgb".format(i=i) for i in range(MAX_INPUTS))
    glsl_sum = " + ".join("texture(map{i}, flipped).rgb".format(i=i) for i in range(MAX_INPUTS))

    return """<fragment uiName="{name}" name="{name}" type="plumbing" class="ShadeFragment" version="1.0" feature_level="20">
  <description><![CDATA[Sums {max_inputs} texture_registry channels for ledFaceBlend.]]></description>
  <keyword value="plumbing" />
  <properties>
    <float2 name="uvCoord" semantic="mayaUvCoordSemantic" flags="varyingInputParam" />
    {map_props}
  </properties>
  <outputs>
    <float3 name="{name}" />
  </outputs>
  <implementation>
    <implementation render="OGSRenderer" language="HLSL" lang_version="11.0">
      <function_name val="{impl_name}" />
      <source>
        <![CDATA[
float3 {impl_name}(float2 uvCoord, {hlsl_params})
{{
    float2 flipped = float2(uvCoord.x, 1.0 - uvCoord.y);
    return {hlsl_sum};
}}
]]>
      </source>
    </implementation>
    <implementation render="OGSRenderer" language="Cg" lang_version="2.1">
      <function_name val="{impl_name}" />
      <source>
        <![CDATA[
float3 {impl_name}(float2 uvCoord, {cg_glsl_params})
{{
    float2 flipped = float2(uvCoord.x, 1.0 - uvCoord.y);
    return {cg_sum};
}}
]]>
      </source>
    </implementation>
    <implementation render="OGSRenderer" language="GLSL" lang_version="3.0">
      <function_name val="{impl_name}" />
      <source>
        <![CDATA[
vec3 {impl_name}(vec2 uvCoord, {cg_glsl_params})
{{
    vec2 flipped = vec2(uvCoord.x, 1.0 - uvCoord.y);
    return {glsl_sum};
}}
]]>
      </source>
    </implementation>
  </implementation>
</fragment>""".format(
        name=name,
        impl_name=impl_name,
        max_inputs=MAX_INPUTS,
        map_props=map_props,
        hlsl_params=hlsl_params,
        cg_glsl_params=cg_glsl_params,
        hlsl_sum=hlsl_sum,
        cg_sum=cg_sum,
        glsl_sum=glsl_sum,
    )


def _ensure_fragment_registered(name):
    try:
        frag_mgr = omr.MRenderer.getFragmentManager()
        _debug.log("LedFaceCapture: ledFaceBlend getFragmentManager() ->", frag_mgr)
        if frag_mgr is None:
            print("LedFaceCapture: no fragment manager -- ledFaceBlend fragment NEVER registered")
            return False
        if frag_mgr.hasFragment(name):
            return True
        fragment_xml = _fragment_xml(name, name + "Impl")
        registered_name = frag_mgr.addShadeFragmentFromBuffer(fragment_xml.encode("utf-8"), False)
        _debug.log("LedFaceCapture: ledFaceBlend fragment registration returned", repr(registered_name))
        return bool(registered_name)
    except Exception:
        _debug.log_exception("node_led_face_blend._ensure_fragment_registered")
        return False


class LedFaceBlend(om2.MPxNode):
    id = NODE_ID

    textureNames = None
    outColor = None

    @staticmethod
    def creator():
        return LedFaceBlend()

    @staticmethod
    def initialize():
        str_fn = om2.MFnTypedAttribute()
        num_fn = om2.MFnNumericAttribute()
        default_string = om2.MFnStringData().create("")

        LedFaceBlend.textureNames = []
        for i in range(MAX_INPUTS):
            str_fn = om2.MFnTypedAttribute()
            attr = str_fn.create(
                "textureName{}".format(i), "tex{}".format(i), om2.MFnData.kString, default_string
            )
            str_fn.storable = True
            str_fn.keyable = False
            om2.MPxNode.addAttribute(attr)
            LedFaceBlend.textureNames.append(attr)

        LedFaceBlend.outColor = num_fn.createColor("outColor", "oc")
        num_fn.storable = False
        num_fn.writable = False
        om2.MPxNode.addAttribute(LedFaceBlend.outColor)


class LedFaceBlendShadingNodeOverride(omr.MPxShadingNodeOverride):
    """Same base-class reasoning as LedFaceShadingNodeOverride in
    node_led_face_material.py: a plain MPxShadingNodeOverride (not the
    Surface subclass), registered via registerShadingNodeOverrideCreator,
    for a utility node that feeds one input on a real shader.
    """

    @staticmethod
    def creator(obj):
        return LedFaceBlendShadingNodeOverride(obj)

    def __init__(self, obj):
        omr.MPxShadingNodeOverride.__init__(self, obj)
        self._node_obj = obj
        self._texture_names = [""] * MAX_INPUTS
        self._sampler_state = None
        # Unique per instance, same reasoning as node_led_face_material.py's
        # FRAGMENT_NAME_PREFIX -- this node is new but there's no reason to
        # repeat that mistake.
        self._fragment_name = "{}_{:08x}".format(FRAGMENT_NAME_PREFIX, id(self) & 0xFFFFFFFF)
        _ensure_fragment_registered(self._fragment_name)

    def supportedDrawAPIs(self):
        return omr.MRenderer.kAllDevices

    def fragmentName(self):
        return self._fragment_name

    def outputForConnection(self, source_plug, destination_plug):
        return self._fragment_name

    def updateDG(self):
        try:
            node_fn = om2.MFnDependencyNode(self._node_obj)
            self._texture_names = [
                node_fn.findPlug("textureName{}".format(i), False).asString()
                for i in range(MAX_INPUTS)
            ]
        except Exception:
            _debug.log_exception("LedFaceBlendShadingNodeOverride.updateDG")
            self._texture_names = [""] * MAX_INPUTS

    def updateShader(self, shader, mappings):
        try:
            if self._sampler_state is None:
                desc = omr.MSamplerStateDesc()
                desc.filter = omr.MSamplerState.kMinMagMipLinear
                desc.addressU = omr.MSamplerState.kTexClamp
                desc.addressV = omr.MSamplerState.kTexClamp
                self._sampler_state = omr.MStateManager.acquireSamplerState(desc)
        except Exception:
            _debug.log_exception("LedFaceBlendShadingNodeOverride.updateShader -- sampler state")

        dummy_black = texture_registry.get_dummy_black()
        # Each slot's setParameter() calls are wrapped separately -- with a
        # single try around the whole loop (the first version of this
        # method), one slot raising (e.g. a name mismatch on "map2") would
        # abort the loop entirely, silently leaving every LATER slot
        # unbound too. ledFaceMaterial's single-texture updateShader() never
        # had this failure mode since it only ever had one slot to begin
        # with -- this is new territory specific to a multi-slot fragment.
        for i, name in enumerate(self._texture_names):
            try:
                texture = texture_registry.get_texture(name) if name else None
                if texture is None:
                    texture = dummy_black
                if texture is None:
                    continue
                texture_assignment = omr.MTextureAssignment()
                texture_assignment.texture = texture
                shader.setParameter("map{}".format(i), texture_assignment)
                if self._sampler_state is not None:
                    shader.setParameter("mapSampler{}".format(i), self._sampler_state)
                _debug.log(
                    "LedFaceCapture: ledFaceBlend updateShader() slot %d textureName=%r -> texture=%r"
                    % (i, name, texture)
                )
            except Exception:
                _debug.log_exception("LedFaceBlendShadingNodeOverride.updateShader -- slot %d" % i)


def register(plugin_fn):
    plugin_fn.registerNode(
        NODE_NAME,
        LedFaceBlend.id,
        LedFaceBlend.creator,
        LedFaceBlend.initialize,
        om2.MPxNode.kDependNode,
        NODE_CLASSIFICATION,
    )
    omr.MDrawRegistry.registerShadingNodeOverrideCreator(
        DRAW_REGISTRY_KEY, DRAW_REGISTRANT_ID, LedFaceBlendShadingNodeOverride.creator
    )


def deregister(plugin_fn):
    omr.MDrawRegistry.deregisterShadingNodeOverrideCreator(DRAW_REGISTRY_KEY, DRAW_REGISTRANT_ID)
    plugin_fn.deregisterNode(LedFaceBlend.id)
