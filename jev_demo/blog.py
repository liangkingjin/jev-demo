"""博客里那几段 Python 代码的可运行版本（客服工单分诊）。

函数体就是文章里贴的代码，只多了 print。跑一遍：

    python -m jev_demo.blog

有 TYPESAFE_API_KEY 就打真接口，没有就走离线 Mock（数字是人造的，结构是真的）。
"""

from __future__ import annotations

from .client import choice_q, noul_q, system_one

# ---------------------------------------------------------------- 部门表

# 组织架构表来自数据库/配置中心，不是模型生成的；描述就是分类规范
DEPARTMENTS = {
    "billing": "账单、扣款、退款、发票、价格争议",
    "technical": "产品故障、报错、装不上、不会操作",
    "delivery": "物流、发错货、没收到、破损",
    "account": "账号、登录、改绑手机、注销",
}

DEPT = choice_q(
    "这条工单该转给哪个部门？只能从给定选项中选。",
    DEPARTMENTS,
)


# ---------------------------------------------------------------- 阈值

def route(answer, min_confidence=0.70, min_probability=0.60):
    """阈值写在签名上：它们是产品决策，应该出现在 code review 里。"""
    if answer["confidence"] < min_confidence:
        return "human", "置信度不够，转人工"
    top = answer["choice"]
    if answer["probabilities"][top] < min_probability:
        return "human", "选项之间分不开，转人工"
    return "auto", top


# ---------------------------------------------------------------- 退款闸门

REFUND_SAFE = noul_q(
    "这笔退款金额合理、理由成立，可以直接原路退回，不需要人工复核",
    true_meaning="金额正常 理由成立 原路退回 小额",
    false_meaning="大额 金额异常 反复申请 可疑 需要审批",
)


def gate(answer, threshold=0.75):
    p = answer["noul"]  # Noul 只有这一个值，没有 confidence
    if p >= threshold:
        return "auto", f"原路退回（P={p:.2f}）"
    return "human", f"P={p:.2f} 未达 {threshold}，转人工审核金额与频次"


# ---------------------------------------------------------------- 工具调用前的挂载点

def check_order(order_id):
    return f"查订单 {order_id} 的物流"


def refund(order_id, amount):
    return f"对订单 {order_id} 退款 {amount} 元"


TOOLS = {"check_order": check_order, "refund": refund}


def guarded_call(tool_name, args, state, question, checker):
    """工具真正执行前，先过一道判定。没过就不执行。"""
    answer = system_one(state, [question])["answers"][0]
    verdict, detail = checker(answer)
    if verdict != "auto":
        return {"ok": False, "stage": "gate", "reason": detail}
    return {"ok": True, "result": TOOLS[tool_name](**args)}


# ---------------------------------------------------------------- 跑一遍

def main():
    print("=" * 70)
    print(" 博客里那几段 Python 代码 · 客服工单分诊 · 实际跑一遍")
    print("=" * 70)

    print("\n[四] 一次请求问一个问题，按阈值分流")
    cases = [
        "扣款扣了两次，账单金额不对，要退款",
        "物流一直没更新，货到现在没收到",
        "在吗",
    ]
    for text in cases:
        answer = system_one(text, [DEPT])["answers"][0]
        verdict, detail = route(answer)
        print(f"  {text:<22} → {verdict:<5} {detail:<10} "
              f"(conf={answer['confidence']:.2f} top={answer['probabilities'][answer['choice']]:.2f})")

    print("\n[五] 部门只能从表里选，编不出一个不存在的部门")
    for text in ["装不上，一直报错，怎么弄", "账单扣款不对，发票也开错了"]:
        answer = system_one(text, [DEPT])["answers"][0]
        verdict, detail = route(answer, min_confidence=0.72, min_probability=0.50)
        if verdict != "auto":
            print(f"  {text:<18} → human {detail}（conf={answer['confidence']:.2f}）")
            continue
        assert detail in DEPARTMENTS, "模型选中了不存在的部门"
        print(f"  {text:<18} → {detail}（{DEPARTMENTS[detail]}）conf={answer['confidence']:.2f}")

    print("\n[附] 退款闸门：同一个 Noul 问题，两个输入")
    for text, amt in [
        ("耳机有杂音，申请退款 金额 89 元 理由成立", 89),
        ("要求退款 大额 8999 元 已经反复申请 三次 可疑", 8999),
    ]:
        answer = system_one(text, [REFUND_SAFE])["answers"][0]
        verdict, detail = gate(answer)
        print(f"  ¥{amt:<6} → {verdict:<5} {detail}")

    print("\n[附] 工具调用前插一道判定")
    for text, amt in [
        ("耳机有杂音，申请退款 金额 89 元 理由成立", 89),
        ("要求退款 大额 8999 元 反复申请 可疑", 8999),
    ]:
        out = guarded_call(
            "refund", {"order_id": "A1024", "amount": amt}, text, REFUND_SAFE, gate
        )
        print(f"  ¥{amt:<6} → {out}")

    print()


if __name__ == "__main__":
    main()
