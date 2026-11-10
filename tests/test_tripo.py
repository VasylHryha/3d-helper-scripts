import json
import tempfile
import unittest
from pathlib import Path

from helpers3d import provenance, tripo


class FakeTripo:
    """Stands in for the network. Records every call so tests can prove nothing was spent."""

    def __init__(self, balance=100, statuses=("running", "success")):
        self.balance = balance
        self.statuses = list(statuses)
        self.calls = []

    def __call__(self, method, url, headers, body):
        path = url.replace(tripo.BASE_URL, "")
        self.calls.append((method, path))
        assert headers.get("Authorization") == "Bearer test-key" or path.startswith("http")
        if path == "/user/balance":
            return 200, json.dumps({"code": 0, "data": {"balance": self.balance, "frozen": 0}}).encode()
        if path == "/upload":
            return 200, json.dumps({"code": 0, "data": {"image_token": "tok-%d" % len(self.calls)}}).encode()
        if path == "/task" and method == "POST":
            self.created = json.loads(body)
            return 200, json.dumps({"code": 0, "data": {"task_id": "task-1"}}).encode()
        if path == "/task/task-1":
            status = self.statuses.pop(0)
            data = {"status": status, "progress": 50, "consumed_credit": 30,
                    "output": {"pbr_model": "https://cdn.example/model.glb"}}
            return 200, json.dumps({"code": 0, "data": data}).encode()
        if path.startswith("https://cdn.example"):
            return 200, b"glb-bytes"
        return 404, b"{}"


def make_images(folder, names):
    paths = {}
    for name in names:
        paths[name] = Path(folder) / (name + ".png")
        paths[name].write_bytes(b"\x89PNG-" + name.encode())
    return paths


class PlanTests(unittest.TestCase):
    def test_kind_follows_inputs_and_describe_needs_no_network(self):
        with tempfile.TemporaryDirectory() as folder:
            views = make_images(folder, ["front", "left", "back", "right"])
            plan = tripo.build_plan(40, views=views)
            self.assertEqual(plan.kind, "multiview_to_model")
            self.assertIn("Credits you say this costs: 40", plan.describe())
            payload = plan.payload({v: "t-" + v for v in views})
            self.assertEqual([f["file_token"] for f in payload["files"]], ["t-front", "t-left", "t-back", "t-right"])

    def test_partial_views_leave_empty_slots(self):
        with tempfile.TemporaryDirectory() as folder:
            views = make_images(folder, ["front", "back"])
            payload = tripo.build_plan(40, views=views).payload({"front": "a", "back": "b"})
            self.assertEqual(payload["files"][1], {})
            self.assertEqual(payload["files"][2]["file_token"], "b")

    def test_needs_credits_and_exactly_one_input(self):
        with self.assertRaises(tripo.TripoError):
            tripo.build_plan(0, prompt="a cube")
        with self.assertRaises(tripo.TripoError):
            tripo.build_plan(10)
        with self.assertRaises(tripo.TripoError):
            tripo.build_plan(10, views={"left": Path("x.png")})


class ExecuteTests(unittest.TestCase):
    def run_execute(self, fake, confirm, folder):
        client = tripo.TripoClient("test-key", transport=fake, sleep=lambda s: None)
        plan = tripo.build_plan(30, views=make_images(folder, ["front", "left"]))
        return tripo.execute(plan, client, confirm, Path(folder) / "out", "thing", Path(folder) / "credits.jsonl",
                             license_note="test licence")

    def test_declined_confirm_makes_no_upload_and_no_task(self):
        with tempfile.TemporaryDirectory() as folder:
            fake = FakeTripo()
            with self.assertRaises(tripo.TripoError):
                self.run_execute(fake, lambda plan, balance: False, folder)
            self.assertEqual([c[1] for c in fake.calls], ["/user/balance"])

    def test_low_balance_stops_before_confirm(self):
        with tempfile.TemporaryDirectory() as folder:
            asked = []
            with self.assertRaises(tripo.TripoError):
                self.run_execute(FakeTripo(balance=10), lambda p, b: asked.append(1) or True, folder)
            self.assertEqual(asked, [])

    def test_full_run_saves_model_log_and_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            fake = FakeTripo()
            model = self.run_execute(fake, lambda plan, balance: True, folder)
            self.assertEqual(model.read_bytes(), b"glb-bytes")
            self.assertEqual(fake.created["type"], "multiview_to_model")
            events = [json.loads(line) for line in (Path(folder) / "credits.jsonl").read_text().splitlines()]
            self.assertEqual([e["event"] for e in events], ["start", "finish"])
            self.assertEqual(events[1]["consumed_credit"], 30)
            self.assertEqual(provenance.verify_record(model), "ok")


class MultipartTests(unittest.TestCase):
    def test_body_holds_file_between_boundaries(self):
        body, content_type = tripo.encode_multipart("file", "a.png", b"DATA", "image/png")
        boundary = content_type.split("boundary=")[1].encode()
        self.assertTrue(body.startswith(b"--" + boundary))
        self.assertIn(b'filename="a.png"', body)
        self.assertTrue(body.rstrip().endswith(b"--" + boundary + b"--"))


if __name__ == "__main__":
    unittest.main()
