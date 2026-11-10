"""Tripo API (v3) client with a spend gate.

Nothing here spends credits unless `execute` is called and its `confirm` callback says yes. `build_plan` and
`Plan.describe` touch neither the network nor the key, so a plan can always be looked at first.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from helpers3d import provenance

BASE_URL = "https://openapi.tripo3d.ai/v3"
VIEW_ORDER = ("front", "left", "back", "right")
ROUTES = {
    "text_to_model": "/generation/text-to-model",
    "image_to_model": "/generation/image-to-model",
    "multiview_to_model": "/generation/multiview-to-model",
    "texture_model": "/models/texture",
}
# Set by the plan itself: --param may not change what the owner was shown.
RESERVED_PARAMS = {"type", "prompt", "input", "inputs", "model"}
MODEL_EXTENSIONS = {".glb", ".gltf", ".fbx", ".obj", ".stl", ".usdz"}
DONE = {"success"}
FAILED = {"failed", "cancelled", "banned", "expired", "unknown"}

# (method, url, headers, body) -> (http status, response bytes)
Transport = Callable[[str, str, Dict[str, str], Optional[bytes]], Tuple[int, bytes]]


class TripoError(RuntimeError):
    pass


def urllib_transport(method: str, url: str, headers: Dict[str, str], body: Optional[bytes]) -> Tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except urllib.error.URLError as error:
        raise TripoError("Network error: %s" % error.reason)


def encode_multipart(field_name: str, filename: str, content: bytes, content_type: str) -> Tuple[bytes, str]:
    boundary = "----h3d" + uuid.uuid4().hex
    head = ('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\nContent-Type: %s\r\n\r\n'
            % (boundary, field_name, filename, content_type)).encode()
    tail = ("\r\n--%s--\r\n" % boundary).encode()
    return head + content + tail, "multipart/form-data; boundary=" + boundary


def image_type(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    if suffix not in ("png", "jpg", "jpeg", "webp"):
        raise TripoError("Unsupported image type %r: use png, jpg or webp." % path.suffix)
    return "jpeg" if suffix == "jpg" else suffix


@dataclass
class PlanInput:
    label: str
    path: Path
    data: bytes = field(repr=False)  # the exact bytes that were hashed, shown and will be uploaded
    sha256: str = ""

    @property
    def size(self) -> int:
        return len(self.data)


class TripoClient:
    def __init__(self, api_key: str, transport: Transport = urllib_transport, base_url: str = BASE_URL,
                 sleep: Callable[[float], None] = time.sleep):
        if not api_key:
            raise TripoError("No Tripo API key. Set TRIPO_API_KEY or put tripo_api_key in the config file.")
        self._key = api_key
        self._transport = transport
        self._base = base_url
        self._sleep = sleep

    def _call(self, method: str, path: str, payload: Any = None, raw_body: Optional[Tuple[bytes, str]] = None) -> dict:
        headers = {"Authorization": "Bearer " + self._key}
        body = None
        if raw_body is not None:
            body, headers["Content-Type"] = raw_body
        elif payload is not None:
            body = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        status, raw = self._transport(method, self._base + path, headers, body)
        try:
            data = json.loads(raw)
        except ValueError:
            raise TripoError("Tripo answered %s with a non-JSON body." % status)
        if status >= 400 or data.get("code", 0) != 0:
            raise TripoError("Tripo error %s on %s: %s" % (status, path, data.get("message") or data))
        return data.get("data") or {}

    def balance(self) -> Dict[str, Any]:
        return self._call("GET", "/account/balance")

    def upload(self, item: PlanInput) -> str:
        kind = image_type(item.path)
        body = encode_multipart("file", item.path.name, item.data, "image/" + kind)
        data = self._call("POST", "/files", raw_body=body)
        token = data.get("file_token") or data.get("image_token")
        if not token:
            raise TripoError("Tripo accepted the upload but returned no file token: %s" % data)
        return token

    def create_task(self, route: str, payload: dict) -> str:
        return self._call("POST", route, payload)["task_id"]

    def task(self, task_id: str) -> dict:
        return self._call("GET", "/tasks/" + task_id)

    def wait(self, task_id: str, poll_seconds: float = 5, timeout: float = 1800,
             on_progress: Optional[Callable[[dict], None]] = None) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            info = self.task(task_id)
            if on_progress:
                on_progress(info)
            status = info.get("status", "unknown")
            if status in DONE:
                return info
            if status in FAILED:
                raise TripoError("Task %s ended as %s." % (task_id, status))
            if time.monotonic() > deadline:
                raise TripoError("Task %s did not finish in %s seconds." % (task_id, timeout))
            self._sleep(poll_seconds)

    def download(self, url: str, destination: Path) -> None:
        status, raw = self._transport("GET", url, {}, None)
        if status >= 400:
            raise TripoError("Download failed with status %s (model links expire after a few minutes: fetch again)."
                             % status)
        destination.write_bytes(raw)


@dataclass
class Plan:
    kind: str
    credits: int
    model: str = ""
    prompt: str = ""
    source_task: str = ""
    inputs: List[PlanInput] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)

    @property
    def route(self) -> str:
        return ROUTES[self.kind]

    def payload(self, tokens: Dict[str, str]) -> dict:
        payload: Dict[str, Any] = {}
        if self.kind == "text_to_model":
            payload["prompt"] = self.prompt
        elif self.kind == "image_to_model":
            payload["input"] = tokens["image"]
        elif self.kind == "multiview_to_model":
            payload["inputs"] = [{view: tokens[view]} for view in VIEW_ORDER if view in tokens]
        else:
            payload["input"] = self.source_task
        if self.model:
            payload["model"] = self.model
        payload.update(self.params)
        return payload

    def describe(self) -> str:
        lines = ["Tripo task: %s (POST %s)" % (self.kind, self.route),
                 "Credits you say this costs: %d (your estimate, not a cap)" % self.credits]
        for item in self.inputs:
            lines.append("Upload %-6s %s  (%d bytes, sha256 %s)" % (item.label, item.path, item.size, item.sha256[:12]))
        preview = self.payload({item.label: "<uploaded %s>" % item.label for item in self.inputs})
        lines.append("Request body: %s" % json.dumps(preview, sort_keys=True))
        return "\n".join(lines)


def _plan_input(label: str, path: Path) -> PlanInput:
    if not path.is_file():
        raise TripoError("Input image not found: %s" % path)
    image_type(path)
    data = path.read_bytes()
    return PlanInput(label, path, data, provenance.sha256_of(path))


def build_plan(credits: int, model: str = "", prompt: str = "", image: Optional[Path] = None,
               views: Optional[Dict[str, Path]] = None, source_task: str = "",
               params: Optional[Dict[str, Any]] = None) -> Plan:
    """The kind follows the inputs: prompt, one image, views (multiview) or a source task id (retexture)."""
    chosen = sum(1 for given in (prompt, image, views, source_task) if given)
    if chosen != 1:
        raise TripoError("Give exactly one of: a prompt, one image, views, or a source task id (retexture).")
    if credits <= 0:
        raise TripoError("State the expected credit cost with --credits (a positive number).")
    params = dict(params or {})
    reserved = sorted(RESERVED_PARAMS & set(params))
    if reserved:
        raise TripoError("--param may not set %s: these come from the plan (use --model, --prompt, inputs)."
                         % ", ".join(reserved))
    plan = Plan(kind="text_to_model", credits=credits, model=model, prompt=prompt, params=params)
    if image:
        plan.kind, plan.inputs = "image_to_model", [_plan_input("image", image)]
    elif views:
        unknown = set(views) - set(VIEW_ORDER)
        if unknown or "front" not in views or len(views) < 2:
            raise TripoError("Views must include front plus at least one of left/back/right (only: %s)."
                             % ", ".join(VIEW_ORDER))
        plan.kind = "multiview_to_model"
        plan.inputs = [_plan_input(v, views[v]) for v in VIEW_ORDER if v in views]
    elif source_task:
        plan.kind, plan.source_task = "texture_model", source_task
    if plan.kind != "texture_model" and not model:
        raise TripoError("State the model with --model (Tripo requires it; its docs recommend a current one, "
                         "for example v3.1-20260211).")
    return plan


def log_credit_event(log_path: Path, event: dict) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    event = dict(event, time_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def model_extension(url: str) -> str:
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    return suffix if suffix in MODEL_EXTENSIONS else ".glb"


def collect(client: TripoClient, task_id: str, out_dir: Path, name: str, log_path: Path,
            license_note: str = "unspecified", on_progress: Optional[Callable[[dict], None]] = None,
            kind: str = "", estimated: Optional[int] = None, inputs: Optional[Dict[str, str]] = None,
            notes: str = "") -> Path:
    """Waits for a task, downloads its model and writes the provenance. Also used to recover a task by its id."""
    try:
        info = client.wait(task_id, on_progress=on_progress)
        output = info.get("output") or {}
        url = output.get("model_url")
        if not url:
            raise TripoError("Task %s succeeded but listed no model_url: %s" % (task_id, sorted(output)))
        out_dir.mkdir(parents=True, exist_ok=True)
        model = out_dir / (name + model_extension(url))
        client.download(url, model)
    except TripoError as error:
        log_credit_event(log_path, {"event": "failed", "task_id": task_id, "error": str(error)})
        raise TripoError("%s Task %s exists: get it back with `fetch --task %s --out %s --name %s`."
                         % (error, task_id, task_id, out_dir, name))
    consumed = info.get("credits_consumed", output.get("credits_consumed"))
    kind = kind or info.get("type", "unknown")
    provenance.write_record(
        model, source="Tripo API (%s)" % kind, tool="3d-helper-scripts", license_note=license_note,
        credits=consumed, task_id=task_id, inputs=inputs or {},
        notes=(notes + " " if notes else "") + ("estimated credits: %s" % estimated if estimated else ""))
    try:
        balance_after = client.balance().get("balance")
    except TripoError:
        balance_after = None
    log_credit_event(log_path, {"event": "finish", "task_id": task_id, "kind": kind,
                                "credits_consumed": consumed, "balance_after": balance_after,
                                "output": model.name})
    return model


def execute(plan: Plan, client: TripoClient, confirm: Callable[[Plan, Dict[str, Any]], bool],
            out_dir: Path, name: str, log_path: Path, license_note: str = "unspecified",
            on_progress: Optional[Callable[[dict], None]] = None,
            on_created: Optional[Callable[[str], None]] = None) -> Path:
    """Checks the balance, asks `confirm`, and only then uploads the reviewed bytes and creates the task."""
    before = client.balance()
    if before.get("balance", 0) < plan.credits:
        raise TripoError("Balance %s is below the %d credits this task needs." % (before.get("balance"), plan.credits))
    if not confirm(plan, before):
        raise TripoError("Not confirmed: no upload was made and no credits were spent.")
    out_dir.mkdir(parents=True, exist_ok=True)
    tokens = {item.label: client.upload(item) for item in plan.inputs}
    task_id = client.create_task(plan.route, plan.payload(tokens))
    log_credit_event(log_path, {"event": "start", "task_id": task_id, "kind": plan.kind,
                                "estimated_credits": plan.credits, "balance_before": before.get("balance")})
    if on_created:
        on_created(task_id)
    inputs = {item.label: item.sha256 for item in plan.inputs}
    if plan.source_task:
        inputs["source_task"] = plan.source_task
    return collect(client, task_id, out_dir, name, log_path, license_note, on_progress, plan.kind, plan.credits,
                   inputs, ("model %s; params %s" % (plan.model, json.dumps(plan.params, sort_keys=True)))
                   + ("; prompt: " + plan.prompt if plan.prompt else ""))
