import maya.cmds as cmds
from UkoreMaya.core import function, menu_utils, utils, Pipeline,Logic,AnimationExporter,RigExporter
from UkoreMaya.menu import General, Rig, Skin

from importlib import reload
from tmlib.core import System


def reload_plugins():
    reload_scripts()

    # Re-import UkoreMaya to re-run its module-level menu registration
    import UkoreMaya
    reload(UkoreMaya)

    try:
        from UkoreMenu import registry
        registry.rebuild_menu()
    except ImportError:
        pass

    cmds.inViewMessage(amg="MayaToolkit Scripts Reloaded!", pos="botCenter", fade=True)


def reload_scripts():
    System.reload_scripts()

    # reload module
    reload(Pipeline)
    reload(function)
    reload(menu_utils)
    reload(utils)
    reload(Logic)
    reload(AnimationExporter)
    reload(RigExporter)
    
    reload(General)
    reload(Rig)
    reload(Skin)
