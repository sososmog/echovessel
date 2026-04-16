"""Hatchling build hook that runs vite build before packaging the wheel.

Purpose
-------
EchoVessel ships a React frontend embedded inside the Python wheel so
end users don't need Node.js installed. The build hook runs
``npm run build`` in ``src/echovessel/channels/web/frontend/`` as part
of ``uv build`` / ``python -m build``, producing static files in
``src/echovessel/channels/web/static/`` which are then force-included
into the wheel via
``[tool.hatch.build.targets.wheel.force-include]`` in ``pyproject.toml``.

Failure modes (all non-fatal unless the build would produce a broken wheel)
---------------------------------------------------------------------------

1. **Frontend directory missing** → warn and skip. Rare; only happens if
   someone deletes ``src/echovessel/channels/web/frontend/`` from a
   sdist-extracted tree. The wheel will still contain whatever is in
   ``static/`` at that moment (possibly empty).

2. **npm not on PATH** → warn and skip. Contributors who only touch the
   Python side shouldn't be blocked from running ``uv build``. The
   wheel uses whatever is already committed / left over in ``static/``.

3. **npm ci / npm run build exit non-zero** → raise ``RuntimeError``.
   This IS fatal because a failed frontend build would produce a wheel
   with stale or missing assets.

4. **Build succeeds but static/ is empty (only contains .gitkeep)** →
   raise ``RuntimeError``. This indicates a misconfigured vite.config.ts
   ``build.outDir``.

Manual alternative
------------------
If you need to run the same steps outside of hatch (e.g. CI builds the
frontend separately and commits static/ before packaging), use
``scripts/build_frontend.sh`` which implements the same flow in bash.

References
----------
- Tracker: ``develop-docs/web-v1/08-stage-8-prep-tracker.md`` §3 Task 5
- Release ops notes: ``develop-docs/web-v1/release-ops.md``
- Release checklist: ``develop-docs/web-v1/99-release-checklist.md``
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class FrontendBuildHook(BuildHookInterface):
    PLUGIN_NAME = "echovessel-frontend"

    def initialize(self, version: str, build_data: dict) -> None:
        """Run vite build before packaging.

        ``initialize`` fires before hatchling collects the file list, so
        any files this method writes into
        ``src/echovessel/channels/web/static/`` will be picked up by the
        ``force-include`` rule in ``pyproject.toml``.

        The hook runs for **both** sdist and wheel targets:

        - Wheel target: directly populates ``static/`` for the
          force-include rule.
        - Sdist target: the populated ``static/`` gets bundled into the
          sdist via the ``include`` list so that downstream wheels
          built from the extracted sdist can resolve their
          ``force-include`` target even if the sdist-build environment
          lacks Node.js.

        This double-coverage means ``uv build`` (the default
        sdist-then-wheel flow) and ``uv build --wheel`` / ``uv build
        --sdist`` all produce consistent output.
        """
        root = Path(self.root)
        frontend_dir = root / "src" / "echovessel" / "channels" / "web" / "frontend"
        static_dir = root / "src" / "echovessel" / "channels" / "web" / "static"

        if not frontend_dir.is_dir():
            self.app.display_warning(
                f"[echovessel-frontend] frontend directory not found at "
                f"{frontend_dir}; skipping frontend build."
            )
            return

        npm = shutil.which("npm")
        if npm is None:
            self.app.display_warning(
                "[echovessel-frontend] npm not found on PATH; skipping "
                "frontend build. Install Node.js (https://nodejs.org) to "
                "build the React bundle, or run "
                "`bash scripts/build_frontend.sh` in a separate shell "
                "before packaging. The wheel will ship with whatever is "
                "currently in src/echovessel/channels/web/static/."
            )
            return

        # Install deps on first run. After that ``node_modules/`` is
        # reused so repeated builds stay fast.
        if not (frontend_dir / "node_modules").is_dir():
            self.app.display_info(
                "[echovessel-frontend] installing frontend dependencies "
                "(npm ci)..."
            )
            subprocess.run(
                [npm, "ci"],
                cwd=frontend_dir,
                check=True,
            )

        self.app.display_info(
            "[echovessel-frontend] running vite build..."
        )
        subprocess.run(
            [npm, "run", "build"],
            cwd=frontend_dir,
            check=True,
        )

        # Sanity check: static dir must contain something more than the
        # .gitkeep sentinel, otherwise vite.config.ts build.outDir is
        # wrong and we'd ship an empty UI.
        if not static_dir.is_dir():
            raise RuntimeError(
                "[echovessel-frontend] static directory missing after "
                f"build: {static_dir}"
            )
        real_files = [
            p for p in static_dir.iterdir() if p.name != ".gitkeep"
        ]
        if not real_files:
            raise RuntimeError(
                "[echovessel-frontend] frontend build completed but "
                f"{static_dir} contains only .gitkeep. Check "
                "src/echovessel/channels/web/frontend/vite.config.ts "
                "build.outDir — it should be '../static'."
            )

        # Restore the .gitkeep sentinel. Vite's `emptyOutDir: true`
        # clobbers the directory before writing its output, so the
        # git-tracked sentinel file gets deleted on every build. That
        # would show up as a spurious "deleted file" in `git status`
        # and, worse, someone could accidentally commit the deletion
        # and lose the directory stub on fresh checkouts. Putting the
        # empty file back after each vite run is idempotent and keeps
        # the git tree clean.
        gitkeep = static_dir / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.touch()

        self.app.display_success(
            f"[echovessel-frontend] frontend build complete "
            f"({len(real_files)} top-level entries in static/)."
        )
