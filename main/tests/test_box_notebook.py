"""验证 Box 教程的几何边界、应用分支及真实 SDK 图像请求契约；不访问网络。"""
import contextlib
import io
import json
import math
import os
import sys
import unittest
from email import message_from_bytes
from pathlib import Path
from unittest.mock import patch

import httpx2
import nbformat
from typesafe_sdk import RetryPolicy, TypeSafeAuthenticationError, TypeSafeClient, TypeSafeError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "generators"))
from build_box_notebook import build_box_notebook
from execute_foundations_notebooks import structure_report


def offline_scope():
    scope = {}
    with patch.dict(os.environ, {"JEV_RUN_MODE": "offline",
                                "TYPESAFE_API_KEY": "", "JEV_BOX_DIR": str(ROOT / "02_核心概念")}), \
            contextlib.redirect_stdout(io.StringIO()):
        for cell in build_box_notebook().cells:
            if cell.cell_type == "code":
                exec(compile(cell.source, f"box:{cell.id}", "exec"), scope)
                scope["display"] = lambda *args, **kwargs: None
    return scope


class BoxNotebookChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope = offline_scope()

    def test_geometry_and_invalid_boxes(self):
        s = self.scope
        truth = (.2, .2, .6, .6)
        self.assertAlmostEqual(s["metrics"]((.4, .2, .8, .6), truth)["iou"], 1/3)
        self.assertEqual(s["metrics"]((.7, .7, .9, .9), truth)["coverage"], 0)
        covering = s["metrics"]((.1, .1, .7, .7), truth)
        self.assertAlmostEqual(covering["coverage"], 1)
        self.assertGreater(covering["area_ratio"], 1)
        self.assertEqual(s["to_pixels"]((.101, .201, .301, .401), (101, 99)),
                         (10, 19, 31, 40))
        for box in ((0, 0, 0, 1), (-.1, 0, 1, 1), (0, 0, math.nan, 1),
                    (0, .6, 1, .2), (0, 0, 1)):
            with self.subTest(box=box), self.assertRaises(ValueError):
                s["as_box"](box)

    def test_padding_and_union_do_not_guarantee_target(self):
        s = self.scope
        truth = s["REFERENCES"]["base"]
        for proposal in s["PROPOSALS"].values():
            before, after = s["metrics"](proposal, truth), s["metrics"](s["padded"](proposal), truth)
            self.assertGreaterEqual(after["coverage"] + 1e-12, before["coverage"])
            self.assertGreaterEqual(after["area_ratio"], before["area_ratio"])
        wrong_union = s["union_box"]((.6, .1, .7, .2), (.7, .2, .8, .3))
        self.assertEqual(s["metrics"](wrong_union, truth)["coverage"], 0)
        wide = s["PROPOSALS"]["偏宽"]
        self.assertLess(s["metrics"](s["padded"](wide), truth)["iou"],
                        s["metrics"](wide, truth)["iou"])

    def test_application_branches_use_scores_not_reference_labels(self):
        decide = self.scope["crop_action"]
        self.assertEqual(decide(.1, .99), "skip")
        self.assertEqual(decide(.99, .1), "review")
        self.assertEqual(decide(.8, .6), "crop")
        audit = self.scope["AUDIT"]
        self.assertEqual((audit["real_calls"], audit["offline_calls"]), (0, 7))
        self.assertEqual(len(audit["results"]["controlled"]), 4)
        self.assertNotIn("absent", self.scope["REFERENCES"])
        self.assertTrue(all(c["response"]["model"] == "offline-demo" for c in audit["calls"]))

    def test_entire_lab_sdk_serialization_with_images(self):
        s = self.scope
        requests = []
        for call_record in s["CALLS"]:
            label = call_record["label"]

            def handler(request):
                self.assertEqual(request.headers["TypeSafe-Danger-Zone-Images"], "true")
                mime = message_from_bytes(
                    ("Content-Type: " + request.headers["content-type"] + "\r\n\r\n").encode()
                    + request.content)
                parts = {part.get_param("name", header="content-disposition"): part
                         for part in mime.walk() if not part.is_multipart()}
                body = json.loads(parts["request"].get_payload(decode=True))
                self.assertEqual(set(body["state"]), {"photo"})
                self.assertEqual(body["questions"], call_record["questions"])
                self.assertNotIn("reference", json.dumps(body["state"]))
                self.assertEqual(body["model"], "jev-1.14.0")
                self.assertEqual(len(body["assets"]), 1)
                requests.append(body)
                return httpx2.Response(200, json={
                    "model": "sdk-contract-test", "answers": s["OFFLINE"][label],
                    "usage": {"input_tokens": 10, "output_tokens": 5}})

            image = (s["IMAGES"].get(label) if label in s["IMAGES"] else
                     s["RING_IMAGE"] if label == "ring" else s["COUPLE_IMAGE"])
            questions = (s["RECT_QUESTIONS"] if label in s["IMAGES"] else
                         s["RING_QUESTIONS"] if label == "ring" else s["COUPLE_QUESTIONS"])
            with TypeSafeClient(api_key="local-test",
                                model="jev-1.14.0", retry=RetryPolicy(max_retries=0),
                                transport=httpx2.MockTransport(handler)) as client, \
                    patch.dict(s, {"MODE": "live", "client": client, "CALLS": []}):
                result = s["call"](label, image, questions)
                self.assertEqual(set(result), set(questions))
                self.assertEqual(s["CALLS"][0]["response"]["model"], "sdk-contract-test")
        self.assertEqual(len(requests), 7)
        self.assertEqual(sum(len(body["questions"]) for body in requests), 17)

    def test_authentication_and_server_failure_never_fall_back(self):
        s = self.scope
        for status, error_type in ((401, TypeSafeAuthenticationError), (500, TypeSafeError)):
            with self.subTest(status=status), TypeSafeClient(
                api_key="local-test", model="jev-1.14.0",
                retry=RetryPolicy(max_retries=0),
                transport=httpx2.MockTransport(
                    lambda request: httpx2.Response(status, json={"detail": "test failure"}))
            ) as client, patch.dict(s, {"MODE": "live", "client": client, "CALLS": []}):
                with self.assertRaises(error_type):
                    s["call"]("base", s["IMAGES"]["base"], s["RECT_QUESTIONS"])
                self.assertEqual(s["CALLS"], [])

    def test_notebook_structure_and_source_provenance(self):
        report = structure_report(build_box_notebook())
        self.assertLessEqual(report["max_code_lines"], 30)
        formal = nbformat.read(ROOT / "02_核心概念/07_box定位.ipynb", as_version=4)
        self.assertEqual([c.source for c in formal.cells if c.cell_type == "code"],
                         [c.source for c in build_box_notebook().cells if c.cell_type == "code"])
        status = formal.metadata["jev_cookbook"]["live_validation"]
        self.assertIn(status, {"pending", "live_executed"})
        if status == "pending":
            self.assertFalse(any(c.get("outputs") for c in formal.cells))


if __name__ == "__main__":
    unittest.main()
