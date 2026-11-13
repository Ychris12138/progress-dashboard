import shutil
import tempfile
import unittest
from pathlib import Path

from dashboard.core import Context, Error, atomic_json, load_public, read_json
from dashboard.render import build

ROOT = Path(__file__).resolve().parents[1]


class FrontendBuildCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dashboard-ui-build-")
        self.base = Path(self.temp.name).resolve()
        self.repo = self.base / "repo"
        self.repo.mkdir()
        shutil.copytree(ROOT / "src", self.repo / "src")
        (self.repo / "tests/fixtures").mkdir(parents=True)
        shutil.copy(ROOT / "tests/fixtures/dashboard-demo.json", self.repo / "tests/fixtures/dashboard-demo.json")
        atomic_json(self.repo / "public/projects.json", {"schema_version": 1, "projects": []})
        self.ctx = Context(self.repo, self.base / "private")

    def tearDown(self):
        self.temp.cleanup()

    def test_synthetic_build_is_explicit_and_outside_public_repo(self):
        with self.assertRaises(Error):
            build(self.ctx, synthetic=True)
        with self.assertRaises(Error):
            build(self.ctx, self.repo / "dist", synthetic=True)
        with self.assertRaises(Error):
            build(self.ctx, self.base / "preview", batch_id="batch_x", synthetic=True)
        result = build(self.ctx, self.base / "preview", synthetic=True)
        self.assertEqual((result["projects"], result["records"]), (6, 9))
        self.assertEqual(load_public(self.repo), ([], []))
        meta = read_json(self.base / "preview/build.json")
        self.assertTrue(meta["synthetic"])
        self.assertTrue(meta["local_preview"])
        self.assertIsNone(meta["actions_url"])

    def test_default_build_never_implicitly_uses_fixture(self):
        build(self.ctx, self.base / "preview", synthetic=True)
        result = build(self.ctx)
        self.assertEqual((result["projects"], result["records"]), (0, 0))
        self.assertFalse(read_json(self.repo / "dist/build.json")["synthetic"])
        self.assertEqual(read_json(self.repo / "dist/data.json")["timeline"], [])

    def test_fixture_must_be_marked_synthetic_and_pass_public_validator(self):
        path = self.repo / "tests/fixtures/dashboard-demo.json"
        fixture = read_json(path)
        fixture["synthetic"] = False
        atomic_json(path, fixture)
        with self.assertRaises(Error):
            build(self.ctx, self.base / "preview", synthetic=True)
        fixture["synthetic"] = True
        fixture["records"][0]["summary"] = "写入 /Users/example/private.txt"
        atomic_json(path, fixture)
        with self.assertRaises(Error):
            build(self.ctx, self.base / "preview", synthetic=True)

    def test_only_runtime_assets_are_in_preview(self):
        build(self.ctx, self.base / "preview", synthetic=True)
        files = {p.name for p in (self.base / "preview").iterdir()}
        self.assertEqual(files, {"index.html", "app.js", "styles.css", "data.json", "build.json"})
        data = read_json(self.base / "preview/data.json")
        states = {p["state_snapshot"]["status"] if p["state_snapshot"] else "unknown" for p in data["projects"]}
        self.assertEqual(states, {"active", "blocked", "done", "paused", "planned", "unknown"})
