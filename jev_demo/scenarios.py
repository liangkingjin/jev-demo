"""四个场景，覆盖 Choice / Noul / Score 三种原语。

场景是一家电商的客服工单分诊：意图路由、部门路由（防编造部门）、
退款闸门、紧急度与退款双问。和 TypeSafe 官方示例是同一类问题。

每个场景声明：questions（真实契约）+ cases（输入）+ decide（阈值与动作）。
decide 是纯函数，接收 answers，返回 (band, action)：
  band = auto   自动执行
       review 二次判定 / 复核
       human  转人工 / 反问用户
"""

from __future__ import annotations

from . import client as C

# 假装从组织架构表查出来的部门（key 是系统里的真实标识）
DEPARTMENTS = {
    "billing": "账单、扣款、退款、发票、价格争议",
    "technical": "产品故障、报错、装不上、不会用",
    "delivery": "物流、发错货、没收到、破损",
    "account": "账号、登录、改绑手机、注销",
}


# ---------------------------------------------------------------- 判定逻辑

def top_p(a):
    """取首选概率，并按两位小数取整，保证「打印多少就按多少判定」。"""
    return round(a["probabilities"][a["choice"]], 2)


def decide_intent(ans):
    a = ans["flow"]
    p = top_p(a)
    if a["choice"] == "needs_review":
        return "human", "模型自己也说不确定，先反问用户"
    if p >= 0.85:
        return "auto", f"直接进入 {a['choice']} 流程"
    if p >= 0.55:
        return "review", f"先问一句「你是要查单还是要退款」再进 {a['choice']}"
    return "human", "转人工 / 澄清诉求"


def decide_dept(ans):
    a = ans["dept"]
    p = top_p(a)
    if p >= 0.80:
        return "auto", f"转 {a['choice']}（这个部门一定存在）"
    if p >= 0.50:
        top2 = sorted(a["probabilities"], key=a["probabilities"].get, reverse=True)[:2]
        return "review", f"给出两个候选部门让用户选：{' / '.join(top2)}"
    return "human", "反问用户具体是账单、物流还是产品问题，不要猜"


def decide_gate(ans):
    p = ans["safe"]["noul"]
    if p >= 0.90:
        return "auto", "原路退回，不进人工"
    if p >= 0.60:
        return "review", "弹二次确认：核对金额与订单号"
    return "human", "不自动退，转人工审核（金额/频次异常）"


def decide_triage(ans):
    refund = ans["refund"]["noul"]
    u = ans["urgency"]
    level = round(u["score"])                      # 等同 jev4j 的 nearestLevel()
    level_name = u["legend"][str(level)]
    if refund >= 0.80:
        return "auto", f"进退款流程（紧急度 {u['score']:.2f} = {level_name}）"
    if level >= 2:
        return "human", f"立即升级人工（紧急度 {u['score']:.2f} = {level_name}）"
    if level == 1:
        return "review", f"排进本周队列（紧急度 {u['score']:.2f} = {level_name}）"
    return "auto", f"正常排队（紧急度 {u['score']:.2f} = {level_name}）"


# ---------------------------------------------------------------- 场景定义

SCENARIOS = [
    {
        "id": "intent",
        "title": "① 意图路由：把「走哪个流程」变成 Choice",
        "why": "选项就是流程清单，低概率不猜，直接进澄清",
        "questions": {
            "flow": C.choice_q(
                "这条客服消息要进哪个处理流程？只能从给定选项中选。",
                {
                    "check_order": "查订单、问物流、问什么时候发货",
                    "refund": "退款、退货、退钱、要求赔偿",
                    "tech_help": "产品用不了、报错、装不上、不会操作",
                    "chitchat": "打招呼、闲聊、与订单无关的问题",
                    "needs_review": "上面都不贴切，或这句话信息不足以判断",
                },
            ),
        },
        "cases": [
            {"label": "明确指令", "state": "我上周买的耳机一直没发货，帮我查下物流到哪了"},
            {"label": "含糊提问", "state": "那个事你们看着办吧"},
        ],
        "decide": decide_intent,
    },
    {
        "id": "dept",
        "title": "② 部门路由：让「转错部门」变成不可能事件",
        "why": "选项来自组织架构表，模型能选错，但选不出一个不存在的部门",
        "questions": {
            "dept": C.choice_q(
                "这条工单该转给哪个部门？只能从给定选项中选。",
                DEPARTMENTS,
            ),
        },
        "cases": [
            {"label": "指向明确", "state": "扣款扣了两次，账单金额不对，要退款"},
            {"label": "跨部门", "state": "账单扣款不对要退款，货也一直没收到，破损了"},
        ],
        "decide": decide_dept,
    },
    {
        "id": "gate",
        "title": "③ 退款闸门：同一句 Noul，两个输入两种结论",
        "why": "问的不是「要不要退」，而是「这笔能不能不惊动人直接退」",
        "questions": {
            "safe": C.noul_q(
                "这笔退款金额合理、理由成立，可以直接原路退回，不需要人工复核",
                true_meaning="金额正常 理由成立 原路退回 小额",
                false_meaning="大额 金额异常 反复申请 可疑 需要审批",
            ),
        },
        "cases": [
            {"label": "正常退款", "state": "耳机有杂音，申请退款 金额 89 元 理由成立"},
            {"label": "异常退款", "state": "要求退款 大额 8999 元 已经反复申请 三次 可疑"},
        ],
        "decide": decide_gate,
    },
    {
        "id": "triage",
        "title": "④ 一次两问：紧急度（Score）+ 是否要退款（Noul）",
        "why": "同一段工单文本上的多个判断，不该拆成两次请求",
        "questions": {
            "urgency": C.score_q(
                "这条工单有多紧急？按影响排，不看客户情绪。",
                ["可以等一周", "本周内处理", "今天必须回复"],
            ),
            "refund": C.noul_q(
                "客户在要求退款吗？",
                true_meaning="退款 退货 退钱 赔偿 冲正",
                false_meaning="只是咨询 开发票 改地址 问进度",
            ),
        },
        "cases": [
            {"label": "崩溃+赶时间", "state": "系统今早就崩了，今天必须上线，现在必须给我解决"},
            {"label": "普通咨询", "state": "想问下能不能补开发票，抬头怎么填"},
        ],
        "decide": decide_triage,
    },
]


def run_all(cli):
    """跑完所有场景，返回可直接渲染的结果结构。"""
    results = []
    for sc in SCENARIOS:
        cases = []
        for case in sc["cases"]:
            resp = cli.system_one(C.request(case["state"], sc["questions"]))
            band, action = sc["decide"](resp["answers"])
            cases.append(
                {
                    "label": case["label"],
                    "state": case["state"],
                    "answers": resp["answers"],
                    "usage": resp.get("usage", {}),
                    "band": band,
                    "action": action,
                }
            )
        results.append(
            {
                "id": sc["id"],
                "title": sc["title"],
                "why": sc["why"],
                "questions": sc["questions"],
                "cases": cases,
            }
        )
    return results
