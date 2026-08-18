import maya.cmds as cmds
import maya.api.OpenMaya as om
from UkoreMaya.core import utils

# ====================================================================
# 1. Setup Marking Menus
# ====================================================================
try:
    utils.setup_marking_menus()
except Exception as e:
    cmds.warning(f"Failed to setup Marking Menus: {e}")

# ====================================================================
# 2. Ukore Reference Editor — automatic scene-open callback
# ====================================================================
# Moved here from the retired maya-plug-ins/ukoreMaya.py. Must be
# registered synchronously (not evalDeferred) — this module is imported
# from MayaToolkit/plugin.py's pre_open_mel launch hook, which runs before
# MayaLauncher's `file -open` in the same launch command, so kAfterOpen
# fires for that very first scene open too, not just later manual opens.
_ukore_reference_editor_callback_id = None


def _on_scene_opened(*_args):
    try:
        from UkoreReferenceEditor import core as ukore_reference_editor_core
    except ImportError:
        return

    try:
        should_open_editor = ukore_reference_editor_core.auto_check_and_redirect()
    except Exception as exc:
        cmds.warning(f"Ukore Reference Editor's automatic check failed: {exc}")
        return

    if should_open_editor:
        try:
            from UkoreMaya.core import menu_utils
            menu_utils.ukore_reference_editor()
        except Exception as exc:
            cmds.warning(f"Ukore Reference Editor failed to open automatically: {exc}")


def _register_ukore_reference_editor_callback():
    global _ukore_reference_editor_callback_id
    if _ukore_reference_editor_callback_id is not None:
        return
    _ukore_reference_editor_callback_id = om.MSceneMessage.addCallback(
        om.MSceneMessage.kAfterOpen, _on_scene_opened
    )


_register_ukore_reference_editor_callback()

# ====================================================================
# 3. Register menu items into ukore_menu's central registry
# ====================================================================
try:
    from UkoreMenu import registry, MenuItemSpec

    items = [
        # --- จัดการไฟล์ (flattened into General, order 10s) ---
        MenuItemSpec(
            id="maya_file_browser",
            label="Maya File Browser...",
            category="General",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.maya_file_browser()",
            order=10,
        ),
        MenuItemSpec(
            id="save_increment",
            label="Save Increment",
            category="General",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.save_increment()",
            order=20,
        ),
        MenuItemSpec(
            id="ukore_reference_editor",
            label="Ukore Reference Editor...",
            category="General",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.ukore_reference_editor()",
            order=30,
        ),

        MenuItemSpec(
            id="fix_sound_offset",
            label="Fix Sound Offset",
            category="General",
            command="import UkoreMaya; from UkoreMaya.library import fix_sound_offset; fix_sound_offset.fix_sound_offset()",
            order=40,
        ),

        # --- Selection (submenu: "Common", order 100s) ---
        MenuItemSpec(
            id="flip_selection",
            label="Flip Selection",
            category="Common",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.flip_selection()",
            icon="flipU.png",
            order=110,
        ),
        MenuItemSpec(
            id="flip_anim_value",
            label="Flip Selection Value...",
            category="Common",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.flip_animation_value()",
            order=120,
        ),
        MenuItemSpec(
            id="print_selected",
            label="Selected (LIST)",
            category="Common",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.print_selected()",
            icon="savePreset.png",
            order=130,
        ),
        MenuItemSpec(
            id="selected_to_dict",
            label="Pair Selected (DICT)",
            category="Common",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.selected_to_dict()",
            icon="savePreset.png",
            order=140,
        ),
        MenuItemSpec(
            id="sort_anim_control",
            label="Anim Control",
            category="Common",
            sub_menu="Sort by Type",
            command='import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.sort_type("anim_curve")',
            order=150,
        ),
        MenuItemSpec(
            id="sort_transform",
            label="transform",
            category="Common",
            sub_menu="Sort by Type",
            command='import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.sort_type("transform")',
            order=151,
        ),
        MenuItemSpec(
            id="sort_joint",
            label="joint",
            category="Common",
            sub_menu="Sort by Type",
            command='import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.sort_type("joint")',
            order=152,
        ),
        MenuItemSpec(
            id="sort_nurbscurve",
            label="nurbsCurve",
            category="Common",
            sub_menu="Sort by Type",
            command='import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.sort_type("nurbsCurve")',
            order=153,
        ),
        MenuItemSpec(
            id="sort_custom",
            label="Custom...",
            category="Common",
            sub_menu="Sort by Type",
            command='import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.sort_type("custom")',
            order=154,
        ),

        # --- Common (submenu: "Common", order 200s) ---
        MenuItemSpec(
            id="renamer",
            label="Renamer",
            category="Common",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.renamer()",
            order=210,
        ),
        MenuItemSpec(
            id="attribute_tool",
            label="Attribute",
            category="Common",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.attribute()",
            order=220,
        ),
        MenuItemSpec(
            id="reset_transform",
            label="Reset Transform",
            category="Common",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.reset_transform()",
            order=230,
        ),
        MenuItemSpec(
            id="smart_parent",
            label="Smart Parent",
            category="Common",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.smart_parent()",
            order=240,
        ),
        MenuItemSpec(
            id="lock_attribute",
            label="Lock Attribute",
            category="Common",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.lock_attr()",
            order=250,
        ),
        MenuItemSpec(
            id="unlock_attribute",
            label="Unlock Attribute",
            category="Common",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.unlock_attr()",
            order=260,
        ),

        # --- Model / Texture (submenu: "Model") ---
        MenuItemSpec(
            id="auto_position_grid",
            label="Auto Position to Grid from Selected",
            category="Model",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.auto_position_to_grid()",
            order=10,
        ),
        MenuItemSpec(
            id="validate_materials",
            label="Validate Selected Materials Naming",
            category="Model",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.validate_material()",
            order=20,
        ),
        MenuItemSpec(
            id="validate_facesets",
            label="Validate Selected Facesets",
            category="Model",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.validate_facesets()",
            order=30,
        ),
        MenuItemSpec(
            id="validate_uv_sets",
            label="Validate Unwanted UV Sets",
            category="Model",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.validate_uv_map()",
            order=40,
        ),
        MenuItemSpec(
            id="cleanup_uvmap",
            label="Remove UV Sets to single sets",
            category="Model",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.cleanup_uvmap()",
            order=50,
        ),
        MenuItemSpec(
            id="export_fbx_single",
            label="Export Selected to Fbx Single...",
            category="Model",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.export_selected_to_substance()",
            order=60,
        ),
        MenuItemSpec(
            id="export_fbx_multiple",
            label="Export Selected to Fbx Multiple...",
            category="Model",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.export_selected_to_multiple()",
            order=70,
        ),
        MenuItemSpec(
            id="model_publish",
            label="Model Publish...",
            category="Model",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.maya_publisher()",
            order=80,
        ),

        # --- Rig (submenu: "Rig") ---
        MenuItemSpec(
            id="local_script",
            label="Local Script...",
            category="Rig",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.python_reader()",
            order=10,
        ),
        MenuItemSpec(
            id="quick_data",
            label="Quick Data",
            category="Rig",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.quickdata()",
            order=20,
        ),
        MenuItemSpec(
            id="easy_controller",
            label="Easy Controller",
            category="Rig",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.easy_controller()",
            order=30,
        ),
        MenuItemSpec(
            id="snapper",
            label="Snapper",
            category="Rig",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.snapper()",
            order=40,
        ),
        MenuItemSpec(
            id="weight_puller",
            label="Weight Puller",
            category="Rig",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.weight_puller()",
            order=50,
        ),
        MenuItemSpec(
            id="advanced_skeleton",
            label="Advanced Skeleton",
            category="Rig",
            sub_menu="External Tools",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.run_advanced()",
            order=60,
        ),
        MenuItemSpec(
            id="advanced_skeleton_face",
            label="Advanced Skeleton Face",
            category="Rig",
            sub_menu="External Tools",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.run_advanced_face()",
            order=61,
        ),
        MenuItemSpec(
            id="ng_skin_tools",
            label="ngSkinTools",
            category="Rig",
            sub_menu="External Tools",
            command="import ngSkinTools2; ngSkinTools2.open_ui()",
            order=62,
        ),
        # Auto Constraint Submenu
        MenuItemSpec(
            id="constraint_all",
            label="Parent + Scale",
            category="Rig",
            sub_menu="Auto Constraint",
            command='import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.auto_constraint("all")',
            order=70,
        ),
        MenuItemSpec(
            id="constraint_parent",
            label="Parent",
            category="Rig",
            sub_menu="Auto Constraint",
            command='import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.auto_constraint("parent")',
            order=71,
        ),
        MenuItemSpec(
            id="constraint_point",
            label="Point",
            category="Rig",
            sub_menu="Auto Constraint",
            command='import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.auto_constraint("point")',
            order=72,
        ),
        MenuItemSpec(
            id="constraint_orient",
            label="Orient",
            category="Rig",
            sub_menu="Auto Constraint",
            command='import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.auto_constraint("orient")',
            order=73,
        ),
        MenuItemSpec(
            id="constraint_scale",
            label="Scale",
            category="Rig",
            sub_menu="Auto Constraint",
            command='import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.auto_constraint("scale")',
            order=74,
        ),
        # Auto Connection Submenu
        MenuItemSpec(
            id="conn_all",
            label="All",
            category="Rig",
            sub_menu="Auto Connection",
            command='import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.auto_connection("all")',
            order=80,
        ),
        MenuItemSpec(
            id="conn_translate",
            label="Translate",
            category="Rig",
            sub_menu="Auto Connection",
            command='import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.auto_connection("translate")',
            order=81,
        ),
        MenuItemSpec(
            id="conn_rotate",
            label="Rotate",
            category="Rig",
            sub_menu="Auto Connection",
            command='import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.auto_connection("rotate")',
            order=82,
        ),
        MenuItemSpec(
            id="conn_scale",
            label="Scale",
            category="Rig",
            sub_menu="Auto Connection",
            command='import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.auto_connection("scale")',
            order=83,
        ),
        MenuItemSpec(
            id="follicle_pin",
            label="Add Follicle Pin",
            category="Rig",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.follicle_pin()",
            order=90,
        ),
        MenuItemSpec(
            id="freeze_group",
            label="Freeze Group",
            category="Rig",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.freeze_group()",
            order=91,
        ),
        MenuItemSpec(
            id="create_joint_set",
            label="Create Joint Set",
            category="Rig",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.create_joint_set()",
            order=92,
        ),
        MenuItemSpec(
            id="copy_mesh_shape",
            label="Copy Mesh Shape",
            category="Rig",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.copy_shape()",
            order=93,
        ),
        MenuItemSpec(
            id="copy_skin_weight",
            label="Copy Skin Weight",
            category="Rig",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.copy_skin_weight()",
            order=94,
        ),
        MenuItemSpec(
            id="add_multi_skin",
            label="Add Multi Skin Cluster",
            category="Rig",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.add_multi_skin()",
            order=95,
        ),
        MenuItemSpec(
            id="rig_publish",
            label="Rig Publish...",
            category="Rig",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.maya_publisher()",
            order=96,
        ),

        # --- Animation (submenu: "Anim") ---
        MenuItemSpec(
            id="dreamwall_picker",
            label="Dreamwall Picker",
            category="Anim",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.dreamwall_picker()",
            order=10,
        ),
        MenuItemSpec(
            id="studio_library",
            label="Studio Library",
            category="Anim",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.studio_library()",
            order=20,
        ),
        MenuItemSpec(
            id="shot_splitter",
            label="Shot Splitter",
            category="Anim",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.shot_splitter()",
            order=30,
        ),
        MenuItemSpec(
            id="playblast",
            label="Playblast",
            category="Anim",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.playblast()",
            order=40,
        ),
        MenuItemSpec(
            id="playblast_options",
            label="Playblast Options...",
            category="Anim",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.playblast_options()",
            order=41,
        ),
        MenuItemSpec(
            id="animation_publish",
            label="Animation Publish...",
            category="Anim",
            command="import UkoreMaya; from UkoreMaya.core import menu_utils; menu_utils.maya_publisher()",
            order=50,
        ),
    ]

    for item in items:
        registry.register_item(item)

except ImportError:
    pass
