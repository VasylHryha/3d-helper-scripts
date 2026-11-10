# 3d-helper-scripts

Small, dependency-free helper scripts for two jobs that come up together when you make game assets with AI:

- **Tripo**: ask the Tripo 3D API for a model, with a built-in **look first, then spend** gate.
- **Blender**: run headless Blender on a model to render views, check the mesh, and convert it, the same way on
  Windows, macOS and Linux.

Everything is plain Python 3.9+ (standard library only). Blender scripts use only what Blender ships. MIT licensed.
This is an independent project, not made or endorsed by Tripo or the Blender Foundation.

## Quick start

```
python3 -m helpers3d --help        # Windows: py -m helpers3d --help
python3 -m helpers3d blender where # finds Blender, or tells you it is missing
```

Optional: `pip install .` gives you the short command `h3d` instead of `python3 -m helpers3d`.

### Tripo key

Get a key from your Tripo account, then either:

- set the environment variable `TRIPO_API_KEY`, or
- create `config.json` containing `{"tripo_api_key": "tsk_..."}` in the settings folder:
  macOS `~/Library/Application Support/3d-helper-scripts/`, Windows `%APPDATA%\3d-helper-scripts\`,
  Linux `~/.config/3d-helper-scripts/`. Set `H3D_HOME` to use another folder.

The key never lives in a project folder, so it cannot be committed by accident.

## Spending credits safely

```
# 1. Dry run: prints what would be sent. No network, no key, no credits.
python3 -m helpers3d tripo plan --credits 40 --front front.png --left left.png --back back.png --right right.png

# 2. Put the upload views side by side and look at them yourself.
python3 -m helpers3d sheet front.png left.png back.png right.png --out out/upload_views.png

# 3. Run. It checks your balance, shows the plan again and waits for you to type the credit number.
python3 -m helpers3d tripo run --credits 40 --front front.png --left left.png --back back.png --right right.png \
    --out out --name my_model --license "my licence note"
```

- `--credits` is your own statement of what the task costs (Tripo's price depends on options and plan). The run stops
  if your balance is lower, and it only continues when you type the same number or pass `--confirm-credits 40`.
- Choose the input kind with `--prompt "..."` (text), `--image x.png` (one image) or `--front/--left/--back/--right`
  (multiview, `--front` required). Extra task options go through `--param key=value` (for example
  `--param model_version=v2.5-20250123`); values are read as JSON when they parse.
- Every run appends to `credits.jsonl` in the settings folder (task id, estimate, credits consumed, balance before and
  after) and writes `<model>.glb.provenance.json` next to the download.
- Check `python3 -m helpers3d tripo balance` any time.

## Blender tools

Blender is found through `BLENDER_BIN`, then the `PATH`, then the newest install in the usual places for your system.
Scripts run with `--factory-startup`, so your add-ons and preferences cannot change the result. Rendering uses
Blender's Workbench engine: no GPU needed and the same output on every platform.

| Command | What it does |
| --- | --- |
| `turntable MODEL --out DIR --frames 24` | Renders `turn_000.png` ... around the model. |
| `views MODEL --out DIR` | Front, left, back, right, top and three-quarter renders plus `views_sheet.png`. |
| `check MODEL --json report.json [--max-tris N] [--strict]` | Triangles, size, materials, textures, missing UVs, loose parts, open edges. `--strict` exits 2 on warnings. |
| `convert IN OUT [--height 1.8] [--ground]` | glb, gltf, fbx, obj or blend to glb, gltf, fbx, obj or blend. Scales to a height and stands the model on z=0. |
| `sheet IMG... --out sheet.png` | Puts images side by side. Use it to look at upload views before a spend. |
| `blender run SCRIPT -- args` | Runs your own script the same headless way. |

View names follow the glTF convention: the model faces -Y, so `left` is the model's own left side.

## Provenance and safety

- `provenance add ASSET --source ... --tool ... --license ...` writes `ASSET.provenance.json` with a SHA-256.
  `provenance verify ASSET` tells you if the file changed since. Keep the licence of every model and rig you use.
- `scan` looks for API keys, private home-folder paths and your own deny-terms before you commit.
  Put one word per line in a local `.scan-terms` file (it is gitignored). Turn it into a commit guard with
  `git config core.hooksPath .githooks`.

## Development

```
python3 -m unittest discover -s tests -v
```

Unit tests mock the Tripo network, so they never spend credits. The Blender smoke test runs when Blender is found.
CI runs the unit tests on Windows, macOS and Linux and the Blender smoke test on Linux.

## Licence

[MIT](LICENSE).
