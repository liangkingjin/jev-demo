"""契约与阈值测试：python -m unittest discover -s tests -t .

重点不是覆盖率，而是三件事：
  1. mock 的回包形状必须和真实 API 一致（不然接 --live 就崩）
  2. 同一输入必须得到同一结果（可复现）
  3. 八个用例的分档必须稳定（改阈值或改权重会被这里抓到）
"""

import unittest

from jev_demo import client as C
from jev_demo import scenarios as S


class TestContract(unittest.TestCase):
    def setUp(self):
        self.cli = C.MockJevClient()
        self.state = "把那副 199 的银耳环加购 一件"
        self.req = C.request(
            self.state,
            {
                "tool": C.choice_q("选哪个工具", {"cart": "加购 放进购物车", "ask": "咨询 问价"}),
                "safe": C.noul_q("是否安全", "明确要求 加购 一件", "三件 多件 数量异常"),
                "urg": C.score_q("多紧急", ["可以等", "本周", "今天"]),
            },
        )

    def test_choice_shape(self):
        a = self.cli.system_one(self.req)["answers"]["tool"]
        self.assertEqual(a["type"], "choice")
        self.assertIn(a["choice"], {"cart", "ask"})
        self.assertAlmostEqual(sum(a["probabilities"].values()), 1.0, places=2)
        self.assertTrue(0.0 <= a["confidence"] <= 1.0)

    def test_noul_shape(self):
        a = self.cli.system_one(self.req)["answers"]["safe"]
        self.assertEqual(a["type"], "noul")
        self.assertTrue(0.0 <= a["noul"] <= 1.0)
        self.assertNotIn("confidence", a, "Noul 没有 confidence 字段，别加")

    def test_score_shape(self):
        a = self.cli.system_one(self.req)["answers"]["urg"]
        self.assertEqual(a["type"], "score")
        self.assertTrue(0.0 <= a["score"] <= 2.0)
        self.assertEqual(set(a["legend"]), {"0", "1", "2"})
        self.assertAlmostEqual(sum(a["probabilities"].values()), 1.0, places=2)

    def test_deterministic(self):
        first = self.cli.system_one(self.req)
        second = self.cli.system_one(self.req)
        self.assertEqual(first["answers"], second["answers"])

    def test_unknown_type(self):
        bad = C.request("x", {"q": {"type": "essay", "instructions": "写一篇"}})
        with self.assertRaises(ValueError):
            self.cli.system_one(bad)


class TestBands(unittest.TestCase):
    """八个用例的落档，就是这套阈值的「金标准」。"""

    EXPECTED = {
        ("intent", "明确指令"): "auto",
        ("intent", "含糊提问"): "human",
        ("catalog", "指向明确"): "auto",
        ("catalog", "跨类目"): "human",
        ("gate", "正常加购"): "auto",
        ("gate", "异常加购"): "human",
        ("triage", "断链+赶时间"): "human",
        ("triage", "普通咨询"): "review",
    }

    def test_bands(self):
        results = S.run_all(C.MockJevClient())
        for sc in results:
            for case in sc["cases"]:
                key = (sc["id"], case["label"])
                with self.subTest(case=key):
                    self.assertEqual(case["band"], self.EXPECTED[key], f"{key} 的分档变了")
                    self.assertTrue(case["action"], "每个判定都要给出动作")

    def test_three_bands_all_present(self):
        bands = {c["band"] for sc in S.run_all(C.MockJevClient()) for c in sc["cases"]}
        self.assertEqual(bands, {"auto", "review", "human"}, "演示必须覆盖三档")


class TestThresholds(unittest.TestCase):
    """直接喂合成答案，验证 decide 的边界。"""

    @staticmethod
    def _choice(p, top="cart"):
        probs = {top: p, "other": round(1 - p, 4)}
        return {"type": "choice", "choice": top, "confidence": 0.5, "probabilities": probs}

    def test_intent_edges(self):
        self.assertEqual(S.decide_intent({"tool": self._choice(0.95)})[0], "auto")
        self.assertEqual(S.decide_intent({"tool": self._choice(0.60)})[0], "review")
        self.assertEqual(S.decide_intent({"tool": self._choice(0.30)})[0], "human")

    def test_gate_edges(self):
        for p, band in [(0.95, "auto"), (0.70, "review"), (0.40, "human")]:
            with self.subTest(p=p):
                self.assertEqual(S.decide_gate({"safe": {"type": "noul", "noul": p}})[0], band)


if __name__ == "__main__":
    unittest.main()
