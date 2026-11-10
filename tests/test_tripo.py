import json
import tempfile
import unittest
from pathlib import Path

from helpers3d import provenance, tripo


class FakeTripo:
    """Stands in for the network. Records every call so tests can prove nothing was spent."""

    def __init__(self, balance=100, statuses=("running", "success"), model_url="https://cdn.example/m.glb?sig=1",
                 fail_download=False):
        self.balance = balance
        self.statuses = list(statuses)
        self.model_url = model_url
        self.fail_download = fail_download
        self.calls = []
        self.created = None
        self.uploaded = []

    def __call__(self, method, url, headers, body):
        path = url.replace(tripo.BASE_URL, "")
        self.calls.append((method, path))
        if path.startswith("/"):
            assert headers.get("Authorization") == "Bearer test-key"
        if path == "/account/balance":
            return 200, json.dumps({"code": 0, "data": {"balance": self.balance, "frozen": 0}}).encode()
        if path == "/files":
            self.uploaded.append(body)
            return 200, json.dumps({"code": 0, "data": {"file_token": "file_%d" % len(self.uploaded)}}).encode()
        if method == "POST":
            self.created = (path, json.loads(body))
            return 200, json.dumps({"code": 0, "data": {"task_id": "task-1"}}).encode()
        if path == "/tasks/task-1":
            status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            data = {"status": status, "progress": 50, "type": "multiview_to_model",
                    "output": {"model_url": self.model_url}, "credits_consumed": 30.0}
            return 200, json.dumps({"code": 0, "data": data}).encode()
        if path.startswith("https://cdn.example"):
            return (500, b"") if self.fail_download else (200, b"glb-bytes")
        return 404, b"{}"


def make_images(folder, names):
    paths = {}
    for name in names:
        paths[name] = Path(folder) / (name + ".png")
        paths[name].write_bytes(b"\x89PNG-" + name.encode())
    return paths


MODEL = "v3.1-20260211"


class PlanTests(unittest.TestCase):
    def test_multiview_body_is_v3_view_keys_and_shown_in_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            views = make_images(folder, ["front", "left", "back", "right"])
            plan = tripo.build_plan(40, MODEL, views=views)
            self.assertEqual(plan.kind, "multiview_to_model")
            self.assertEqual(plan.route, "/generation/multiview-to-model")
            payload = plan.payload({v: "t-" + v for v in views})
            self.assertEqual(payload["inputs"], [{"front": "t-front"}, {"left": "t-left"},
                                                 {"back": "t-back"}, {"right": "t-right"}])
            self.assertEqual(payload["model"], MODEL)
            self.assertIn('"model": "%s"' % MODEL, plan.describe())

    def test_each_kind_has_its_own_route_and_body(self):
        with tempfile.TemporaryDirectory() as folder:
            image = make_images(folder, ["one"])["one"]
            self.assertEqual(tripo.build_plan(5, MODEL, prompt="a cube").payload({}),
                             {"prompt": "a cube", "model": MODEL})
            plan = tripo.build_plan(5, MODEL, image=image)
            self.assertEqual((plan.route, plan.payload({"image": "f1"})),
                             ("/generation/image-to-model", {"input": "f1", "model": MODEL}))
            retexture = tripo.build_plan(5, source_task="abc", params={"texture_quality": "detailed"})
            self.assertEqual((retexture.route, retexture.payload({})),
                             ("/models/texture", {"input": "abc", "texture_quality": "detailed"}))

    def test_param_cannot_replace_what_was_reviewed(self):
        for key in ("type", "prompt", "input", "inputs", "model"):
            with self.assertRaises(tripo.TripoError):
                tripo.build_plan(5, MODEL, prompt="a cube", params={key: "x"})

    def test_needs_credits_model_and_exactly_one_input(self):
        with self.assertRaises(tripo.TripoError):
            tripo.build_plan(0, MODEL, prompt="a cube")
        with self.assertRaises(tripo.TripoError):
            tripo.build_plan(10, MODEL)
        with self.assertRaises(tripo.TripoError):
            tripo.build_plan(10, "", prompt="a cube")
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(tripo.TripoError):
                tripo.build_plan(10, MODEL, views=make_images(folder, ["front"]))
            with self.assertRaises(tripo.TripoError):
                tripo.build_plan(10, MODEL, views={"left": Path("x.png"), "back": Path("y.png")})


class ExecuteTests(unittest.TestCase):
    def run_execute(self, fake, confirm, folder, **kwargs):
        client = tripo.TripoClient("test-key", transport=fake, sleep=lambda s: None)
        plan = tripo.build_plan(30, MODEL, views=make_images(folder, ["front", "left"]))
        return tripo.execute(plan, client, confirm, Path(folder) / "out", "thing", Path(folder) / "credits.jsonl",
                             license_note="test licence", **kwargs)

    def test_declined_confirm_makes_no_upload_and_no_task(self):
        with tempfile.TemporaryDirectory() as folder:
            fake = FakeTripo()
            with self.assertRaises(tripo.TripoError):
                self.run_execute(fake, lambda plan, balance: False, folder)
            self.assertEqual([c[1] for c in fake.calls], ["/account/balance"])

    def test_low_balance_stops_before_confirm(self):
        with tempfile.TemporaryDirectory() as folder:
            asked = []
            with self.assertRaises(tripo.TripoError):
                self.run_execute(FakeTripo(balance=10), lambda p, b: asked.append(1) or True, folder)
            self.assertEqual(asked, [])

    def test_full_run_uploads_reviewed_bytes_and_records_everything(self):
        with tempfile.TemporaryDirectory() as folder:
            fake = FakeTripo()
            created = []
            model = self.run_execute(fake, lambda plan, balance: True, folder, on_created=created.append)
            self.assertEqual(created, ["task-1"])
            self.assertEqual(model.name, "thing.glb")
            self.assertEqual(model.read_bytes(), b"glb-bytes")
            self.assertEqual(fake.created[0], "/generation/multiview-to-model")
            self.assertEqual(fake.created[1]["inputs"], [{"front": "file_1"}, {"left": "file_2"}])
            self.assertIn(b"\x89PNG-front", fake.uploaded[0])
            events = [json.loads(line) for line in (Path(folder) / "credits.jsonl").read_text().splitlines()]
            self.assertEqual([e["event"] for e in events], ["start", "finish"])
            self.assertEqual(events[1]["credits_consumed"], 30.0)
            self.assertEqual(provenance.verify_record(model), "ok")
            record = json.loads(provenance.record_path(model).read_text())
            self.assertIn(MODEL, record["notes"])

    def test_download_keeps_the_real_extension(self):
        with tempfile.TemporaryDirectory() as folder:
            model = self.run_execute(FakeTripo(model_url="https://cdn.example/m.fbx?sig=1"),
                                     lambda p, b: True, folder)
            self.assertEqual(model.suffix, ".fbx")

    def test_failed_download_logs_failure_and_names_the_recovery_command(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(tripo.TripoError) as caught:
                self.run_execute(FakeTripo(fail_download=True), lambda p, b: True, folder)
            self.assertIn("fetch --task task-1", str(caught.exception))
            events = [json.loads(line) for line in (Path(folder) / "credits.jsonl").read_text().splitlines()]
            self.assertEqual([e["event"] for e in events], ["start", "failed"])

    def test_fetch_recovers_a_task_by_id(self):
        with tempfile.TemporaryDirectory() as folder:
            client = tripo.TripoClient("test-key", transport=FakeTripo(), sleep=lambda s: None)
            model = tripo.collect(client, "task-1", Path(folder) / "out", "again", Path(folder) / "credits.jsonl")
            self.assertEqual(model.read_bytes(), b"glb-bytes")
            self.assertIn("multiview_to_model", provenance.record_path(model).read_text())


class MultipartTests(unittest.TestCase):
    def test_body_holds_file_between_boundaries(self):
        body, content_type = tripo.encode_multipart("file", "a.png", b"DATA", "image/png")
        boundary = content_type.split("boundary=")[1].encode()
        self.assertTrue(body.startswith(b"--" + boundary))
        self.assertIn(b'filename="a.png"', body)
        self.assertTrue(body.rstrip().endswith(b"--" + boundary + b"--"))


if __name__ == "__main__":
    unittest.main()
