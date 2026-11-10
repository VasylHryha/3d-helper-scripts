"""Command line: `python3 -m helpers3d <command>` (Windows: `py -m helpers3d <command>`)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from helpers3d import blender, config, provenance, scan, tripo


def _params(pairs: List[str]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for pair in pairs or []:
        key, _, value = pair.partition("=")
        try:
            result[key] = json.loads(value)
        except ValueError:
            result[key] = value
    return result


def _plan_from_args(args) -> tripo.Plan:
    views = {v: Path(getattr(args, v)) for v in tripo.VIEW_ORDER if getattr(args, v)}
    return tripo.build_plan(args.credits, args.prompt or "", Path(args.image) if args.image else None,
                            views or None, _params(args.param))


def _make_confirm(confirm_credits: Optional[int]):
    def confirm(plan: tripo.Plan, balance: dict) -> bool:
        print(plan.describe())
        print("Balance now: %s" % balance.get("balance"))
        if confirm_credits is not None:
            return confirm_credits == plan.credits
        answer = input("Look at the upload views first. Type %d to spend that many credits, anything else cancels: "
                       % plan.credits)
        return answer.strip() == str(plan.credits)
    return confirm


def cmd_tripo(args) -> int:
    if args.action == "plan":
        print(_plan_from_args(args).describe())
        print("\nDry run only: nothing was uploaded and no credits were spent.")
        return 0
    plan = _plan_from_args(args) if args.action == "run" else None
    client = tripo.TripoClient(config.tripo_key() or "")
    if args.action == "balance":
        print(json.dumps(client.balance()))
        return 0
    model = tripo.execute(plan, client, _make_confirm(args.confirm_credits), Path(args.out), args.name,
                          config.credit_log_path(), args.license,
                          on_progress=lambda info: print("  status %s %s%%" % (info.get("status"), info.get("progress", "?"))))
    print("Saved %s" % model)
    return 0


def cmd_blender(args) -> int:
    found = blender.find_blender()
    if args.action == "where":
        print(found or "Blender not found")
        return 0 if found else 1
    script = Path(args.script) if args.script else None
    return blender.run_script(script, args.rest, found)


def _builtin(name: str, rest: List[str]) -> int:
    return blender.run_script(blender.scripts_dir() / name, rest)


def cmd_turntable(args) -> int:
    return _builtin("turntable.py", ["--model", args.model, "--out", args.out, "--frames", str(args.frames),
                                     "--size", str(args.size)])


def cmd_views(args) -> int:
    return _builtin("views.py", ["--model", args.model, "--out", args.out, "--size", str(args.size)])


def cmd_check(args) -> int:
    extra = ["--max-tris", str(args.max_tris)] if args.max_tris else []
    extra += ["--strict"] if args.strict else []
    return _builtin("mesh_check.py", ["--model", args.model, "--json", args.json] + extra)


def cmd_convert(args) -> int:
    extra = ["--height", str(args.height)] if args.height else []
    extra += ["--ground"] if args.ground else []
    return _builtin("convert.py", ["--model", args.model, "--out", args.out] + extra)


def cmd_sheet(args) -> int:
    return _builtin("sheet.py", ["--out", args.out, "--columns", str(args.columns), "--cell", str(args.cell),
                                 "--images"] + args.images)


def cmd_provenance(args) -> int:
    asset = Path(args.asset)
    if args.action == "verify":
        status = provenance.verify_record(asset)
        print(status)
        return 0 if status == "ok" else 1
    path = provenance.write_record(asset, args.source, args.tool, args.license, args.credits, notes=args.notes)
    print("Wrote %s" % path)
    return 0


def cmd_scan(args) -> int:
    return scan.main(args.staged, Path(args.root))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="h3d", description="Tripo and Blender helper scripts.")
    sub = parser.add_subparsers(dest="command", required=True)

    tr = sub.add_parser("tripo", help="plan (free dry run), balance, or run (spends credits after confirm)")
    tr.add_argument("action", choices=["plan", "balance", "run"])
    tr.add_argument("--credits", type=int, default=0, help="credits you expect this to cost (plan, run)")
    tr.add_argument("--prompt")
    tr.add_argument("--image")
    for view in tripo.VIEW_ORDER:
        tr.add_argument("--" + view, help="%s view for multiview_to_model" % view)
    tr.add_argument("--param", action="append", default=[], metavar="KEY=VALUE")
    tr.add_argument("--out", default="out", help="folder for the downloaded model")
    tr.add_argument("--name", default="model", help="file name without extension")
    tr.add_argument("--license", default="unspecified", help="licence note for the provenance record")
    tr.add_argument("--confirm-credits", type=int, help="non-interactive confirm: must equal --credits")
    tr.set_defaults(func=cmd_tripo)

    bl = sub.add_parser("blender", help="where: print the Blender found; run: run a script in Blender")
    bl.add_argument("action", choices=["where", "run"])
    bl.add_argument("script", nargs="?")
    bl.add_argument("rest", nargs=argparse.REMAINDER)
    bl.set_defaults(func=cmd_blender)

    tt = sub.add_parser("turntable", help="render frames around a model")
    tt.add_argument("model"); tt.add_argument("--out", default="out/turntable")
    tt.add_argument("--frames", type=int, default=24); tt.add_argument("--size", type=int, default=512)
    tt.set_defaults(func=cmd_turntable)

    vw = sub.add_parser("views", help="render front/left/back/right/top/three-quarter plus a contact sheet")
    vw.add_argument("model"); vw.add_argument("--out", default="out/views"); vw.add_argument("--size", type=int, default=512)
    vw.set_defaults(func=cmd_views)

    ck = sub.add_parser("check", help="mesh report: triangles, bounds, UVs, textures, loose parts, holes")
    ck.add_argument("model"); ck.add_argument("--json", default="out/mesh_check.json")
    ck.add_argument("--max-tris", type=int); ck.add_argument("--strict", action="store_true")
    ck.set_defaults(func=cmd_check)

    cv = sub.add_parser("convert", help="convert between glb/fbx/obj/blend, optionally scale and ground")
    cv.add_argument("model"); cv.add_argument("out")
    cv.add_argument("--height", type=float, help="scale to this height in metres")
    cv.add_argument("--ground", action="store_true", help="centre on the origin and stand on z=0")
    cv.set_defaults(func=cmd_convert)

    sh = sub.add_parser("sheet", help="put images side by side in one picture (look at upload views before a spend)")
    sh.add_argument("images", nargs="+"); sh.add_argument("--out", default="out/sheet.png")
    sh.add_argument("--columns", type=int, default=4); sh.add_argument("--cell", type=int, default=512)
    sh.set_defaults(func=cmd_sheet)

    pv = sub.add_parser("provenance", help="write or verify the record next to an asset")
    pv.add_argument("action", choices=["add", "verify"]); pv.add_argument("asset")
    pv.add_argument("--source", default="unknown"); pv.add_argument("--tool", default="unknown")
    pv.add_argument("--license", default="unspecified"); pv.add_argument("--credits", type=int)
    pv.add_argument("--notes", default="")
    pv.set_defaults(func=cmd_provenance)

    sc = sub.add_parser("scan", help="find keys, private paths and deny-terms in the repo")
    sc.add_argument("--staged", action="store_true"); sc.add_argument("--root", default=".")
    sc.set_defaults(func=cmd_scan)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (tripo.TripoError, FileNotFoundError) as error:
        print("error: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
