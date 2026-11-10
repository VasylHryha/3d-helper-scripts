"""Tripo API client with a spend gate.

Nothing here spends credits unless `execute` is called and its `confirm` callback says yes. `build_plan` and
`Plan.describe` touch neither the network nor the key, so a plan can always be looked at first.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from helpers3d import provenance

BASE_URL = "https://api.tripo3d.ai/v2/openapi"
VIEW_ORDER = ("front", "left", "back", "right")
OUTPUT_KEYS = ("pbr_model", "model", "base_model")
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
    return "jpg" if suffix == "jpeg" else suffix


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
        return self._call("GET", "/user/balance")

    def upload(self, path: Path) -> str:
        kind = image_type(path)
        body = encode_multipart("file", path.name, path.read_bytes(), "image/" + ("jpeg" if kind == "jpg" else kind))
        data = self._call("POST", "/upload", raw_body=body)
        token = data.get("image_token") or data.get("file_token")
        if not token:
            raise TripoError("Tripo accepted the upload but returned no token: %s" % data)
        return token

    def create_task(self, payload: dict) -> str:
        return self._call("POST", "/task", payload)["task_id"]

    def task(self, task_id: str) -> dict:
        return self._call("GET", "/task/" + task_id)

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
            raise TripoError("Download failed with status %s." % status)
        destination.write_bytes(raw)


@dataclass
class PlanInput:
    label: str
    path: Path
    sha256: str
    size: int


@dataclass
class Plan:
    kind: str
    credits: int
    prompt: str = ""
    inputs: List[PlanInput] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)

    def payload(self, tokens: Dict[str, str]) -> dict:
        payload: Dict[str, Any] = {"type": self.kind}
        if self.kind == "text_to_model":
            payload["prompt"] = self.prompt
        elif self.kind == "image_to_model":
            item = self.inputs[0]
            payload["file"] = {"type": image_type(item.path), "file_token": tokens[item.label]}
        else:
            by_label = {item.label: item for item in self.inputs}
            payload["files"] = [
                {"type": image_type(by_label[v].path), "file_token": tokens[v]} if v in by_label else {}
                for v in VIEW_ORDER]
        payload.update(self.params)
        return payload

    def describe(self) -> str:
        lines = ["Tripo task: %s" % self.kind, "Credits you say this costs: %d" % self.credits]
        if self.prompt:
            lines.append("Prompt: %s" % self.prompt)
        for item in self.inputs:
            lines.append("Upload %-6s %s  (%d bytes, sha256 %s)" % (item.label, item.path, item.size, item.sha256[:12]))
        if self.params:
            lines.append("Extra parameters: %s" % json.dumps(self.params, sort_keys=True))
        return "\n".join(lines)


def _plan_input(label: str, path: Path) -> PlanInput:
    if not path.is_file():
        raise TripoError("Input image not found: %s" % path)
    image_type(path)
    return PlanInput(label, path, provenance.sha256_of(path), path.stat().st_size)


def build_plan(credits: int, prompt: str = "", image: Optional[Path] = None,
               views: Optional[Dict[str, Path]] = None, params: Optional[Dict[str, Any]] = None) -> Plan:
    """The kind follows the inputs: a prompt is text_to_model, one image is image_to_model, views are multiview."""
    chosen = sum(1 for given in (prompt, image, views) if given)
    if chosen != 1:
        raise TripoError("Give exactly one of: a prompt, one image, or views (front plus any of left/back/right).")
    if credits <= 0:
        raise TripoError("State the expected credit cost with --credits (a positive number).")
    plan = Plan(kind="text_to_model", credits=credits, prompt=prompt, params=dict(params or {}))
    if image:
        plan.kind, plan.inputs = "image_to_model", [_plan_input("image", image)]
    elif views:
        unknown = set(views) - set(VIEW_ORDER)
        if unknown or "front" not in views:
            raise TripoError("Views must include front and only use: %s." % ", ".join(VIEW_ORDER))
        plan.kind = "multiview_to_model"
        plan.inputs = [_plan_input(v, views[v]) for v in VIEW_ORDER if v in views]
    return plan


def log_credit_event(log_path: Path, event: dict) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    event = dict(event, time_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def execute(plan: Plan, client: TripoClient, confirm: Callable[[Plan, Dict[str, Any]], bool],
            out_dir: Path, name: str, log_path: Path, license_note: str = "unspecified",
            on_progress: Optional[Callable[[dict], None]] = None) -> Path:
    """Checks the balance, asks `confirm`, and only then uploads and creates the task."""
    before = client.balance()
    if before.get("balance", 0) < plan.credits:
        raise TripoError("Balance %s is below the %d credits this task needs." % (before.get("balance"), plan.credits))
    if not confirm(plan, before):
        raise TripoError("Not confirmed: no upload was made and no credits were spent.")
    tokens = {item.label: client.upload(item.path) for item in plan.inputs}
    task_id = client.create_task(plan.payload(tokens))
    log_credit_event(log_path, {"event": "start", "task_id": task_id, "kind": plan.kind,
                                "estimated_credits": plan.credits, "balance_before": before.get("balance")})
    info = client.wait(task_id, on_progress=on_progress)
    output = info.get("output") or {}
    url = next((output[key] for key in OUTPUT_KEYS if output.get(key)), None)
    if not url:
        raise TripoError("Task %s succeeded but listed no model file: %s" % (task_id, sorted(output)))
    out_dir.mkdir(parents=True, exist_ok=True)
    model = out_dir / (name + ".glb")
    client.download(url, model)
    after = client.balance()
    log_credit_event(log_path, {"event": "finish", "task_id": task_id, "kind": plan.kind,
                                "consumed_credit": info.get("consumed_credit"),
                                "balance_after": after.get("balance"), "output": model.name})
    provenance.write_record(
        model, source="Tripo API (%s)" % plan.kind, tool="3d-helper-scripts", license_note=license_note,
        credits=info.get("consumed_credit", plan.credits), task_id=task_id,
        inputs={item.label: item.sha256 for item in plan.inputs},
        notes=("prompt: " + plan.prompt) if plan.prompt else "")
    return model
