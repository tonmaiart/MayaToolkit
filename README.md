# plugins/repo_internal/MayaToolkit/

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
`maya-plug-ins/ukoreMaya.py`'s Model/Rig/Animation menus.
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
setup, all `registry.register_item()` calls, and the Ukore Reference
Editor's `kAfterOpen` scene-open callback — moved here from the old
`ukoreMaya.py`'s `initializePlugin`) actually run every Maya session.
Deliberately `pre_open_mel`, not `post_open_mel`: the reference-editor
callback must be registered before MayaLauncher's `file -open` (which
runs *after* `pre_open_mel` but *before* `post_open_mel` — see
`maya_launcher/README.md`'s `_build_launch_commands` step order), or the
auto-check misses the very first scene open — the exact bug already fixed
once when this lived in the force-loaded plug-in (see
`developer/bug-history/2026-08-05-reference-editor-callback-registered-too-late-for-first-open.md`
in the dev repo). `UkoreMaya/core/Plugin.py`'s `reload_plugins()` no
longer unloads/reloads a `ukoreMaya` Maya plug-in either — it just
re-imports/reloads the `UkoreMaya` package and calls
`UkoreMenu.registry.rebuild_menu()`.
# MayaToolkit
