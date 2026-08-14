from __future__ import annotations

from pathlib import Path

TOOL_ID = "maya_toolkit"
TOOL_LABEL = "MayaToolkit"
# Convention-only string match with plugins/repo_internal/maya_launcher/plugin.py
# — both resolve to the same active Project's plugin_data via
# ProjectPluginConfigStore, no coupling API needed. See that plugin's README
# for the full "contributions"/"labels" shape this writes into.
MAYA_ENV_BRIDGE_PLUGIN_ID = "maya_launcher_env_bridge"
ANY_VERSION = "*"


def register(api) -> None:
    tool_root = Path(__file__).resolve().parent

    bridge = api.project_plugin_config_store(MAYA_ENV_BRIDGE_PLUGIN_ID)
    if bridge is None:
        return
    contributions = bridge.get("contributions", {})
    contributions[TOOL_ID] = {
        "PYTHONPATH": {ANY_VERSION: [str(tool_root / "maya-scripts")]},
    }
    bridge.set("contributions", contributions)
    labels = bridge.get("labels", {})
    labels[TOOL_ID] = TOOL_LABEL
    bridge.set("labels", labels)

    # No longer a MAYA_PLUG_IN_PATH plug-in — menu now lives in ukore_menu's
    # central registry instead of its own menu, so UkoreMaya just needs to be
    # imported once per Maya session for its module-level registration/
    # callback setup to run. Must be pre_open_mel, not post_open_mel: this
    # import also registers the Ukore Reference Editor's kAfterOpen scene
    # callback (see UkoreMaya/__init__.py), which has to be in place before
    # the very first `file -open` MayaLauncher issues later in the same
    # launch command — post_open_mel runs after that file -open and would
    # miss the first scene's auto-check (the exact bug the old force-loaded
    # ukoreMaya.py plug-in worked around by registering the callback
    # synchronously in initializePlugin instead of evalDeferred).
    hooks = bridge.get("launch_hooks", {})
    hooks[TOOL_ID] = {
        "order": 10,
        "pre_open_mel": 'python("try:\\n    import UkoreMaya\\nexcept ImportError:\\n    pass");',
    }
    bridge.set("launch_hooks", hooks)
