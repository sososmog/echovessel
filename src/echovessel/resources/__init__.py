"""Packaged resource files bundled into the EchoVessel wheel.

This package exists purely as a target for :func:`importlib.resources.files`.
Any file added here must also be listed in the wheel force-include rule in
``pyproject.toml`` so hatchling includes it in the built artifact — resources
are NOT auto-detected by hatchling for non-``.py`` files.

Currently bundled:

- ``config.toml.sample`` — starter TOML that ``echovessel init`` copies to
  ``~/.echovessel/config.toml`` (see ``echovessel.runtime.launcher.init``).
"""
