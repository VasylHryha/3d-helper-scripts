# Contributing

- Python standard library only: no dependencies for the command line tools. Blender scripts may use `bpy` and
  `numpy` (Blender ships both).
- Everything must work on Windows, macOS and Linux. Use `pathlib`, never hard-code a path separator or a user folder.
- Run `python3 -m unittest` before you open a pull request. The Blender smoke test runs when Blender is found.
- Add a test only for a behaviour you add or a real bug you fix.
- Run `python3 -m helpers3d scan` and `git config core.hooksPath .githooks` so no key or private path is committed.
- Anything that spends Tripo credits must go through the dry-run and confirm step in `helpers3d/tripo.py`.
