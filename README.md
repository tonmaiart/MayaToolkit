# plugins/repo_internal/MayaToolkit/

**2026-08-31: Renamer/Attribute/PythonReader ("Local Script")/QuickData/
EasyController/Snapper/WeightPuller — removed, moved to
`cache/plugins/RigToolkit/`.** These toolkit folders no longer lived under
this plugin's `maya-scripts/` at all (only `UkoreMaya/` and `tmlib/`
remained here — the menu items calling them were dangling), so they were
never actually reachable through this plugin any more. `RigToolkit` now
owns both the implementations (`RigToolkit/<Name>/interface.py`, same
`tmlib.core.File.launch("<Name>")` convention) and their menu registration:
its own `plugin.py` contributes its own root folder to the
`maya_launcher_env_bridge` `PYTHONPATH` and its own `launch_hooks` entry
(`import UkoreRigToolkit`), and `RigToolkit/UkoreRigToolkit/__init__.py`
registers the same `"renamer"`/`"attribute_tool"`/`"local_script"`/
`"quick_data"`/`"easy_controller"`/`"snapper"`/`"weight_puller"` `UkoreMenu`
items directly (same ids/order/category as before, so this is a no-op for
anyone using the menu) — same pattern as the AdvancedSkeleton/
UkoreReferenceEditor/ShotSplitter splits above.
`UkoreMaya/core/menu_utils.py`'s corresponding wrapper functions were
removed too.

**2026-09-01: `UkoreMaya/custom_library/` removed, moved to
`cache/plugins/RigToolkit/PythonReader/custom_library/`.** These scripts
were only ever reachable through `RigToolkit/PythonReader`'s
config-driven "Global Paths" function browser (removed the same day, see
RigToolkit's own README) — nothing in `MayaToolkit` itself imported this
folder. They still `import UkoreMaya`/`from UkoreMaya.core import ...`/
`from UkoreMaya.menu import ...` directly from their new home, which
keeps resolving at runtime through the shared `maya_launcher_env_bridge`
PYTHONPATH merge (`RigToolkit` declares `requires: ["maya_toolkit", ...]`
in its `manifest.json`) — same flat-namespace convention `File.launch()`
itself already relies on, so this is not a new coupling.

MayaToolkit — UkoreHub's own vendored Maya scripts and plug-ins (Renamer,
RigBox, WeightPuller, `tmlib`, `UkoreMaya`, and friends, under
`maya-scripts/`), plus compiled plug-ins under `maya-plug-ins/`. Unchanged
internal layout from the original `add-on/MayaToolkit/` (moved to
`plugins/repo_internal/maya_launcher/MayaToolkit/` during the 2026-07-14
consolidation, then split back out to its own top-level plugin here on
2026-07-19 — see `plugins/repo_internal/maya_launcher/README.md` for why).

**UkorePublisher was extracted out of `maya-scripts/UkorePublisher/` on
2026-07-19** into its own top-level plugin, then split again the same day
into three type-specific plugins — `ModelPublisher`, `RigPublisher`,
`AnimationPublisher` — all built on the new
`plugins/repo_internal/PublishApi/` shared library instead of a single
shared UI/publish-path convention. `UkoreMaya/core/menu_utils.py`'s old
single `publisher()` function became three:
`model_publisher()`/`rig_publisher()`/`animation_publisher()`, each
calling `tmlib.core.File.launch("ModelPublisher")`/`"RigPublisher"`/
`"AnimationPublisher"`. **2026-08-05**: those three plugins were merged
back into one `plugins/repo_internal/MayaPublisher/` (a per-repo "Publish
Mode" setting picks Rig/Model/Animation instead of enabling a separate
plugin per mode) — `menu_utils.py`'s three functions collapsed into one
`maya_publisher()` calling `File.launch("MayaPublisher")`, still wired up
from the same three "...Publish..." menu items under
`maya-plug-ins/ukoreMaya.py`'s Model/Rig/Animation menus. **2026-08-20**:
MayaPublisher's own in-window category picker (`comboBox_tickets_catagory`,
see its README) made those three menu items redundant duplicates of each
other — all three opened the exact same window — so they and
`menu_utils.maya_publisher()` were removed from `UkoreMaya/__init__.py`/
`menu_utils.py`; the tool is launched instead from MayaPublisher's own
single "Maya Publisher..." item under General
(`plugins/repo_internal/MayaPublisher/maya-scripts/MayaPublisher/__init__.py`).
`File.launch` resolves by Python module name (`import <Name>`), not by
filesystem nesting, so this works the same way it always has once each
plugin's own `plugin.py` contributes its `PYTHONPATH` entry to the bridge
(see below).

Like every other Maya tool plugin here, this does **not** launch Maya
itself and has no UI of its own inside UkoreHub — `plugin.py`'s
`register(api)` writes a `PYTHONPATH` (`maya-scripts/`) contribution into
`plugins/repo_internal/maya_launcher/`'s shared `maya_launcher_env_bridge`
`PluginConfigStore`, read and merged by that plugin's `open_maya_file`
when it actually launches Maya. No direct import relationship with
`maya_launcher` — just the shared `PluginConfigStore` id convention (see
that plugin's README for the full bridge shape). Repository Setting >
Enable Plugin (`Repo.required_plugin_ids`) is what lets a studio admin
disable this tool per-repo; this plugin always contributes unconditionally.

**2026-08-14: `maya-plug-ins/ukoreMaya.py` retired — no more
`MAYA_PLUG_IN_PATH` contribution, no more own menu.** UkoreMaya no longer
builds its own "Ukore Studio Tool" Maya menu; all of its menu items now
register into `plugins/repo_internal/ukore_menu/`'s central "Ukore Tools"
registry instead (`UkoreMenu.registry.register_item()` /
`UkoreMenu.MenuItemSpec` — see that plugin's README for the full API).
`plugin.py`'s `register(api)` instead writes a `launch_hooks` entry into
the same `maya_launcher_env_bridge` bridge: `order: 10`, `pre_open_mel`
that does `import UkoreMaya` — this is what makes
`maya-scripts/UkoreMaya/__init__.py`'s module-level code (marking-menu
setup and all `registry.register_item()` calls) actually run every Maya
session. `UkoreMaya/core/Plugin.py`'s `reload_plugins()` no longer
unloads/reloads a `ukoreMaya` Maya plug-in either — it just re-imports/
reloads the `UkoreMaya` package and calls `UkoreMenu.registry.rebuild_menu()`.

**2026-08-20: Ukore Reference Editor's automatic `kAfterOpen` scene-open
callback and its "Ukore Reference Editor..." menu item — both dispatched
from here since the `ukoreMaya.py` retirement above — removed.**
`plugins/repo_internal/UkoreReferenceEditor/` now registers both itself,
independent of MayaToolkit: its own `plugin.py` contributes its own
`pre_open_mel` launch hook (`import UkoreReferenceEditor`, same
before-`file -open` timing this plugin's own hook uses and for the same
reason — see that plugin's own README/bug-history for why registering
after the first `file -open` misses it), and its own `__init__.py`
registers the `kAfterOpen` callback and the `UkoreMenu` item directly.
Keeping a second copy here duplicate-registered the same
`"ukore_reference_editor"` menu id into `UkoreMenu`'s registry and
double-ran the auto-fix on every scene open — removed rather than left as
harmless redundancy.

**2026-08-27: AdvancedSkeleton's "Advanced Skeleton"/"Advanced Skeleton
Face" menu items (Rig > External Tools) — removed.**
`cache/plugins/ukore_advanced_skeleton/` now registers both itself,
independent of MayaToolkit: its own `plugin.py` contributes its own
`launch_hooks` entry (`import UkoreAdvancedSkeleton`), and its own
`maya-scripts/UkoreAdvancedSkeleton/__init__.py` registers the same
`"advanced_skeleton"`/`"advanced_skeleton_face"` `UkoreMenu` items and a
reload handler directly — same ids/order/submenu as before, so this is a
no-op for anyone using the menu. `UkoreMaya/core/function.py`'s
`_advanced_skeleton_root()`/`run_advance()`/`run_advance_face()` and
`menu_utils.py`'s `run_advanced()`/`run_advanced_face()` wrappers moved
there too. `ukore_advanced_skeleton/plugin.py` also had two real bugs
fixed in the same change: it computed its own `maya-scripts` path via
`api.app_root / "plugins" / "studio" / "AdvancedSkeleton"` (stale from
before its 2026-07-19 split into a standalone `cache/plugins/` clone —
that path doesn't exist any more) instead of `Path(__file__).resolve().parent`,
and it wrote its `PYTHONPATH`/`ADVANCEDSKELETON_ROOT` contribution into
the shared studio-wide `plugin_config_store(..., shared=True)` store
instead of the per-project `project_plugin_config_store(...)` store
`maya_launcher`/`MayaToolkit`/`ukore_menu` actually read from — so the
contribution never reached Maya Launcher's env bridge at all.
# MayaToolkit
