"""Jev（TypeSafe System One）最小客户端。

两个后端共用同一份 JSON 契约：
  MockJevClient  —— 离线，用「选项描述与输入文本的字面重合度」模拟判定，结果可复现
  LiveJevClient  —— 真打 https://api.typesafe.ai/v1/systemone

契约（与官方一致）：
  请求 {model, state, questions}
  问题 {type: choice|noul|score, instructions, criteria}
  响应 {model, answers, usage}
    choice -> {type, choice, confidence, probabilities}
    noul   -> {type, noul}
    score  -> {type, score, confidence, legend, probabilities}
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import urllib.request

MODEL = "jev-1.13.0"
ENDPOINT = "https://api.typesafe.ai/v1/systemone"


# ---------------------------------------------------------------- 请求构造

def request(state, questions, model=MODEL):
    """state 可以是字符串，也可以是 dict（结构化快照）。"""
    return {"model": model, "state": state, "questions": questions}


def choice_q(instructions, options):
    """options: {选项名: 描述}，描述就是分类规范，写清楚边界。"""
    return {"type": "choice", "instructions": instructions, "criteria": options}


def noul_q(instructions, true_meaning=None, false_meaning=None):
    q = {"type": "noul", "instructions": instructions}
    if true_meaning or false_meaning:
        q["criteria"] = {"true": true_meaning or "", "false": false_meaning or ""}
    return q


def score_q(instructions, levels):
    """levels: 有序列表，从低到高，等级编号从 0 起。"""
    return {"type": "score", "instructions": instructions, "criteria": list(levels)}


# ---------------------------------------------------------------- 离线模拟

def _noise(*parts):
    """确定性噪声：同一输入永远得到同一个数，便于复现和写测试。"""
    h = hashlib.md5("|".join(parts).encode("utf-8")).digest()
    return h[0] / 255.0


def _grams(text):
    """极简分词：先去掉空格与标点，再取 2 字滑窗。

    只用 2-gram 是有意的：3-gram 会和 2-gram 重复计数，把一句话里
    一个词命中成 3~4 次，概率直接饱和到 1.0。
    """
    text = "".join(c for c in text.lower() if c.isalnum() or ord(c) > 0x2E80)
    return {text[i:i + 2] for i in range(len(text) - 1)}


def _overlap(desc, state_grams):
    return sum(1 for g in _grams(desc) if g in state_grams)


def _concentration(probs):
    """confidence = 分布的集中度（不是最大概率本身）。

    最大值等于均匀分布时 -> 0；只有一项非零时 -> 1。
    兼容传入 dict 或 list。
    """
    values = list(probs.values()) if isinstance(probs, dict) else list(probs)
    n = len(values)
    if n <= 1:
        return 1.0
    top = max(values)
    return max(0.0, min(1.0, (top - 1.0 / n) / (1.0 - 1.0 / n)))


def _state_text(state):
    return state if isinstance(state, str) else json.dumps(state, ensure_ascii=False)


class MockJevClient:
    """离线后端。所有概率都由字面重合度 + 确定性噪声算出来，不是真模型。"""

    name = "MOCK"
    banner = "离线模拟（字面重合度 + 确定性噪声），不是真模型"

    def __init__(self, model=MODEL):
        self.model = model

    def system_one(self, req):
        text = _state_text(req["state"])
        sg = _grams(text)
        qs = req["questions"]
        # 内部场景用 dict 带名字，博客里的写法用 list（与真实接口一致），两种都收
        pairs = list(qs.items()) if isinstance(qs, dict) else list(enumerate(qs))
        answers = {}
        for name, q in pairs:
            if q["type"] == "choice":
                answers[name] = self._choice(q, text, sg)
            elif q["type"] == "noul":
                answers[name] = self._noul(q, text, sg)
            elif q["type"] == "score":
                answers[name] = self._score(q, text, sg)
            else:
                raise ValueError(f"未知问题类型: {q['type']}")
        return {
            "model": self.model,
            "answers": answers,
            "usage": {
                "input_tokens": max(64, int(len(text + json.dumps(qs, ensure_ascii=False)) / 2.2)),
                "output_tokens": 48 * len(pairs),
            },
        }

    def _choice(self, q, text, sg):
        weights = {}
        for opt, desc in q["criteria"].items():
            hits = min(_overlap(desc, sg), 4)          # 重合度封顶，避免一句话把某项拉到 1.0
            weights[opt] = (0.12 + 1.9 * hits) * (0.90 + 0.20 * _noise(text, opt))
        total = sum(weights.values())
        probs = {k: v / total for k, v in weights.items()}
        return {
            "type": "choice",
            "choice": max(probs, key=probs.get),
            "confidence": round(_concentration(probs), 4),
            "probabilities": {k: round(v, 4) for k, v in probs.items()},
        }

    def _noul(self, q, text, sg):
        crit = q.get("criteria") or {}
        pos = _overlap(crit.get("true") or q["instructions"], sg)
        neg = _overlap(crit.get("false") or " ", sg) if crit.get("false") else 0
        logit = 0.9 * (pos - neg) + 2.0 * (_noise(text, q["instructions"]) - 0.5)
        return {"type": "noul", "noul": round(1.0 / (1.0 + math.exp(-logit)), 4)}

    def _score(self, q, text, sg):
        levels = q["criteria"]
        weights = [0.10 + 1.9 * min(_overlap(lv, sg), 3) + 0.25 * _noise(text, str(i))
                   for i, lv in enumerate(levels)]
        total = sum(weights)
        probs = [w / total for w in weights]
        return {
            "type": "score",
            "score": round(sum(i * p for i, p in enumerate(probs)), 4),
            "confidence": round(_concentration(probs), 4),
            "legend": {str(i): lv for i, lv in enumerate(levels)},
            "probabilities": {str(i): round(p, 4) for i, p in enumerate(probs)},
        }


# ---------------------------------------------------------------- 真实后端

def system_one(state, questions, model=MODEL, client=None):
    """博客 4.1 贴的就是这个函数：一次请求问多个问题，返回整个响应。

    有 TYPESAFE_API_KEY 走真接口，没有就走离线 Mock——契约完全一样，
    所以 `system_one(...)["answers"]` 这种写法在两种模式下都不用改。
    """
    if client is None:
        client = LiveJevClient(model=model) if os.environ.get("TYPESAFE_API_KEY") else MockJevClient(model=model)
    raw = client.system_one(request(state, questions, model))
    # 真实接口的 answers 是数组，顺序与 questions 一致；Mock 内部用 dict，这里统一成数组
    answers = raw["answers"]
    if isinstance(answers, dict):
        raw = dict(raw, answers=list(answers.values()))
    return raw


class LiveJevClient:
    """真打 TypeSafe。需要环境变量 TYPESAFE_API_KEY。

    注意：这里刻意不做重试——jev4j 的设计也是「失败就抛，不伪装成 false」。
    """

    name = "LIVE"
    banner = "真实调用 api.typesafe.ai/v1/systemone"

    def __init__(self, api_key=None, model=MODEL, timeout=15.0):
        self.api_key = api_key or os.environ.get("TYPESAFE_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("缺少 TYPESAFE_API_KEY 环境变量")
        self.model = model
        self.timeout = timeout

    def system_one(self, req):
        req = dict(req, model=self.model)
        body = json.dumps(req, ensure_ascii=False).encode("utf-8")
        http_req = urllib.request.Request(
            ENDPOINT,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(http_req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
