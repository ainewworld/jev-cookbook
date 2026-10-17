"""验证图像教程的证据位置、完整概率、序列标签与异常处理；不访问网络。"""
import contextlib
import io
import json
import os
import sys
import unittest
from email import message_from_bytes
from pathlib import Path
from unittest.mock import patch

import httpx2
from typesafe_sdk import RetryPolicy, TypeSafeAuthenticationError, TypeSafeClient, TypeSafeError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "generators"))
from build_images_notebook import build_images_notebook
from execute_foundations_notebooks import structure_report


def offline_scope():
    scope = {}
    captured = []
    with patch.dict(os.environ, {"JEV_RUN_MODE": "offline", "TYPESAFE_API_KEY": "",
                                "JEV_IMAGES_DIR": str(ROOT / "02_核心概念")}), \
            contextlib.redirect_stdout(io.StringIO()):
        for cell in build_images_notebook().cells:
            if cell.cell_type != "code":
                continue
            exec(compile(cell.source, f"images:{cell.id}", "exec"), scope)
            scope["display"] = lambda *args, **kwargs: None
            if "def call(label," in cell.source:
                original = scope["call"]

                def captured_call(label, state, questions):
                    if scope["MODE"] == "offline":
                        captured.append((label, state, questions))
                    return original(label, state, questions)

                scope["call"] = captured_call
    return scope, captured


class ImagesNotebookChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope, cls.captured = offline_scope()

    def test_complete_offline_coverage_and_probabilities(self):
        s = self.scope
        self.assertEqual((s["AUDIT"]["real_calls"], s["AUDIT"]["offline_calls"]), (0, 15))
        self.assertEqual(len(s["PROBES"]), 2)
        self.assertEqual(sum(len(q) for _, _, q in self.captured), 23)
        for record in s["CALLS"]:
            self.assertEqual(record["response"]["model"], "offline-demo")
            for answer in record["response"]["answers"].values():
                if "probabilities" in answer:
                    self.assertAlmostEqual(sum(answer["probabilities"].values()), 1)

    def test_all_requests_pass_real_sdk_with_expected_asset_placement(self):
        s = self.scope
        seen = []
        for label, state, questions in self.captured:
            def handler(request):
                self.assertEqual(request.headers["TypeSafe-Danger-Zone-Images"], "true")
                mime = message_from_bytes(
                    ("Content-Type: " + request.headers["content-type"] + "\r\n\r\n").encode()
                    + request.content)
                parts = {part.get_param("name", header="content-disposition"): part
                         for part in mime.walk() if not part.is_multipart()}
                body = json.loads(parts["request"].get_payload(decode=True))
                seen.append(body)
                if label in s["PHOTO_KEYS"]:
                    self.assertEqual(set(body["state"]), {"photo"})
                    self.assertEqual(len(body["assets"]), 1)
                    self.assertNotIn("about", body["state"])
                if label.startswith("reference_"):
                    self.assertEqual(len(body["assets"]), 2)
                    self.assertIn("reference", body["questions"]["same"]["instructions"])
                if label.startswith("sticker_"):
                    self.assertEqual(len(body["assets"]), 6)
                    self.assertEqual(set(body["questions"]["match"]["criteria"]),
                                     {*s["STICKERS"], "none"})
                if label.startswith("ended_"):
                    self.assertEqual(len(body["state"]["frames"]), 3)
                    self.assertTrue(all(set(f) == {"seconds_ago", "frame"}
                                        for f in body["state"]["frames"]))
                if label == "cost_duplicate":
                    self.assertEqual(body["state"], {})
                    self.assertEqual(len(body["assets"]), 1)
                    self.assertEqual(body["questions"]["face"]["instructions"]["photo"],
                                     body["questions"]["composition"]["instructions"]["photo"])
                return httpx2.Response(200, json={"model": "sdk-contract-test",
                    "answers": s["OFFLINE"][label],
                    "usage": {"input_tokens": 10, "output_tokens": 1}})
            with TypeSafeClient(api_key="local-test", model="jev-1.14.0",
                    transport=httpx2.MockTransport(handler),
                    retry=RetryPolicy(max_retries=0)) as client, \
                    patch.dict(s, {"MODE": "live", "client": client, "CALLS": []}):
                response = s["call"](label, state, questions)
                self.assertEqual(response.model, "sdk-contract-test")
        self.assertEqual(len(seen), 15)

    def test_score_uses_zero_based_levels_and_expected_value(self):
        s = self.scope
        self.assertEqual(len(s["FRAME_QUESTIONS"]["openness"].criteria), 3)
        for answers in s["FRAME_RESULTS"].values():
            answer = answers["openness"]
            self.assertEqual(set(map(float, answer.probabilities)), {0, 1, 2})
            self.assertAlmostEqual(answer.score,
                sum(float(k)*p for k, p in answer.probabilities.items()))

    def test_bad_probabilities_are_rejected(self):
        from typesafe_sdk import SystemOneResponse
        s = self.scope
        answer = dict(s["OFFLINE"]["cafe_selfie"]["composition"])
        answer["probabilities"] = {key: .5 for key in s["SCENES"]}
        response = SystemOneResponse.model_validate({
            "model": "test", "usage": {}, "answers": {
                "face": s["OFFLINE"]["cafe_selfie"]["face"], "composition": answer}})
        with self.assertRaises(ValueError):
            s["validate"](response, s["PHOTO_QUESTIONS"])

    def test_auth_and_server_errors_do_not_become_demo_or_expected_rejection(self):
        s = self.scope
        for status, expected in ((401, TypeSafeAuthenticationError), (500, TypeSafeError)):
            with self.subTest(status=status), TypeSafeClient(api_key="local-test",
                    transport=httpx2.MockTransport(
                        lambda request: httpx2.Response(status, json={"detail": "failure"})),
                    retry=RetryPolicy(max_retries=0)) as client, \
                    patch.dict(s, {"MODE": "live", "client": client, "CALLS": [], "PROBES": []}):
                with self.assertRaises(expected):
                    s["call"]("cafe_selfie", {"photo": s["PHOTO_ASSETS"]["cafe_selfie"]},
                              s["PHOTO_QUESTIONS"])
                with self.assertRaises(expected):
                    s["probe"]("missing", s["PHOTO_ASSETS"]["cafe_selfie"], {}, "Images")
                self.assertEqual(s["CALLS"], [])
                self.assertEqual(s["PROBES"], [])

    def test_only_matching_http_rejection_is_accepted(self):
        s = self.scope
        with TypeSafeClient(api_key="local-test", transport=httpx2.MockTransport(
                lambda request: httpx2.Response(400, json={"detail": "Invalid image dimensions"})),
                retry=RetryPolicy(max_retries=0)) as client, \
                patch.dict(s, {"MODE": "live", "client": client, "PROBES": []}), \
                contextlib.redirect_stdout(io.StringIO()):
            s["probe"]("size", s["PHOTO_ASSETS"]["cafe_selfie"], s["HEADERS"], "dimensions")
            self.assertEqual(s["PROBES"][0]["status"], 400)
            with self.assertRaises(TypeSafeError):
                s["probe"]("header", s["PHOTO_ASSETS"]["cafe_selfie"], {}, "Danger-Zone")

    def test_structure_and_matching_source(self):
        import nbformat
        generated = build_images_notebook()
        self.assertLessEqual(structure_report(generated)["max_code_lines"], 30)
        formal = nbformat.read(ROOT / "02_核心概念/06_图像输入.ipynb", as_version=4)
        self.assertEqual([c.source for c in generated.cells if c.cell_type == "code"],
                         [c.source for c in formal.cells if c.cell_type == "code"])


if __name__ == "__main__":
    unittest.main()
