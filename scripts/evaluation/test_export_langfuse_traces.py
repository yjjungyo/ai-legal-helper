"""Run: python -m unittest -v test_export_langfuse_traces.py (from this directory)."""
import csv
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

here = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("export_langfuse_traces", here / "export_langfuse_traces.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class FakeResponse:
    def __init__(self, obj):
        self.obj = obj
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False
    def read(self):
        return json.dumps(self.obj).encode("utf-8")


class LangfuseExportTests(unittest.TestCase):
    def setUp(self):
        self.trace = "d860ca38-be7a-42d2-acc3-eba8d97d7131"
        self.reader = mod.LangfuseReader("http://localhost:3001", "fake-pk", "fake-sk", timeout=1)

    def test_v3_combines_paginated_observations(self):
        calls = []
        obs1 = [{"id": f"obs{i}", "traceId": self.trace, "type": "SPAN", "input": "secret_value"} for i in range(100)]
        obs2 = [{"id": "last", "traceId": self.trace, "type": "GENERATION", "output": "done"}]
        def fake_open(req, timeout):
            url = req.full_url
            calls.append(url)
            if "/traces/" in url:
                return FakeResponse({"id": self.trace, "observations": obs1[:2], "projectId": mod.DEFAULT_PROJECT})
            if "page=1" in url:
                return FakeResponse({"data": obs1, "meta": {"totalPages": 2}})
            return FakeResponse({"data": obs2, "meta": {"totalPages": 2}})
        with patch.object(mod.urllib.request, "urlopen", side_effect=fake_open):
            raw, mode, warnings = self.reader.export(self.trace)
        self.assertEqual(len(raw["observations"]), 101)
        self.assertEqual(mode, "legacy_trace_v1_observations")
        self.assertEqual(warnings, [])
        self.assertEqual(len(calls), 3)
        self.assertEqual(raw["observations"][100]["output"], "done")

    def test_v4_cursor_pagination(self):
        urls = []
        def fake_open(req, timeout):
            u = req.full_url
            urls.append(u)
            if "/traces/" in u:
                raise urllib.error.HTTPError(u, 404, "not found", {}, io.BytesIO(b""))
            if "cursor=" not in u:
                return FakeResponse({"data": [{"id": "a", "traceId": self.trace, "input": "hello"}], "meta": {"cursor": "next1"}})
            return FakeResponse({"data": [{"id": "b", "traceId": self.trace, "output": "world"}], "meta": {}})
        with patch.object(mod.urllib.request, "urlopen", side_effect=fake_open):
            raw, mode, warnings = self.reader.export(self.trace)
        self.assertEqual(mode, "v2_observations")
        self.assertEqual([x["id"] for x in raw["observations"]], ["a", "b"])
        self.assertEqual(len(urls), 3)

    def test_401_is_error_not_fallback(self):
        def fail(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b""))
        with patch.object(mod.urllib.request, "urlopen", side_effect=fail):
            with self.assertRaises(mod.ApiError) as raised:
                self.reader.export(self.trace)
        self.assertEqual(raised.exception.status, 401)
        self.assertNotIn("fake-sk", str(raised.exception))

    def test_cross_trace_observation_rejected(self):
        with self.assertRaises(ValueError):
            self.reader._validate_rows([{"id": "bad", "traceId": "other"}], self.trace, "fake")

    def test_manifest_25_unique(self):
        rows = mod.read_manifest(mod.DEFAULT_MANIFEST)
        self.assertEqual(len(rows), 25)
        self.assertEqual(len({r["trace_id"] for r in rows}), 25)
        self.assertTrue(mod.safe_filename(rows[-1]).startswith("SC-003_step1_LegalAgent_E2E_V8"))

    def test_run_single_creates_json_and_zip_without_keys(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out"
            env = Path(d) / "local.env"
            env.write_text("LANGFUSE_HOST=http://localhost:3001\nLANGFUSE_PUBLIC_KEY=pk-test\nLANGFUSE_SECRET_KEY=sk-sensitive\n", encoding="utf-8")
            def fake_export(reader, trace_id):
                return {"id": trace_id, "observations": [{"id": "ob1", "traceId": trace_id, "output": "Legal conclusion"}]}, "v2_observations", []
            with patch.object(mod.LangfuseReader, "export", new=fake_export):
                rc=mod.main(["--trace-id", self.trace, "--env-file", str(env), "--out", str(out), "--zip", "--delay", "0"])
            self.assertEqual(rc, 0)
            js = list(out.glob("*.json"))
            self.assertEqual(len(js), 2)
            self.assertTrue((out.parent / "out.zip").is_file())
            for p in js:
                text = p.read_text(encoding="utf-8")
                self.assertNotIn("sk-sensitive", text)
                self.assertNotIn("pk-test", text)
            manifest = json.loads((out / "export_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["success"], 1)
            self.assertEqual(manifest["failed"], 0)


if __name__ == "__main__":
    unittest.main()
