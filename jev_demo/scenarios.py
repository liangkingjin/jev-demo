"""四个场景，覆盖 Choice / Noul / Score 三种原语。

场景照搬博客第五节的导购 Agent：意图路由、类目选择（防 category_id 幻觉）、
加购闸门、紧急度与退款双问。

每个场景声明：questions（真实契约）+ cases（输入）+ decide（阈值与动作）。
decide 是纯函数，接收 answers，返回 (band, action)：
  band = auto   自动执行
       review 二次判定 / 复核
       human  转人工 / 反问用户
"""

from __future__ import annotations

from . import client as C

# 假装从数据库 category 表聚合出来的类目（cid -> 路径）
CATALOG = {
    "11": "项链 / 锁骨链 / 吊坠",
    "12": "戒指 / 对戒 / 素圈",
    "13": "耳饰：耳钉、耳环、耳坠、耳骨夹",
    "14": "手链 / 手镯 / 串珠",
    "15": "脚链 / 其它配饰",
}


# ---------------------------------------------------------------- 判定逻辑

def top_p(a):
    """取首选概率，并按两位小数取整，保证「打印多少就按多少判定」。"""
    return round(a["probabilities"][a["choice"]], 2)


def decide_intent(ans):
    a = ans["tool"]
    p = top_p(a)
    if a["choice"] == "needs_review":
        return "human", "模型自己也说不确定，先反问用户"
    if p >= 0.85:
        return "auto", f"直接调用工具 {a['choice']}"
    if p >= 0.55:
        return "review", f"先问一句「你是想看看，还是直接下单」再执行 {a['choice']}"
    return "human", "转人工 / 澄清需求"


def decide_catalog(ans):
    a = ans["cid"]
    p = top_p(a)
    if p >= 0.80:
        return "auto", f"用 category_id={a['choice']} 查商品（这个 ID 一定存在）"
    if p >= 0.50:
        top2 = sorted(a["probabilities"], key=a["probabilities"].get, reverse=True)[:2]
        return "review", f"给出两个候选类目让用户选：{' / '.join(top2)}"
    return "human", "反问用户要哪一类，不要猜 ID"


def decide_gate(ans):
    p = ans["safe"]["noul"]
    if p >= 0.90:
        return "auto", "直接加入购物车"
    if p >= 0.60:
        return "review", "弹二次确认：确认商品与数量"
    return "human", "不下单，转人工核对（数量/价格异常）"


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
        "title": "① 意图路由：把「调哪个工具」变成 Choice",
        "why": "选项就是工具清单，低概率不猜，直接进澄清流程",
        "questions": {
            "tool": C.choice_q(
                "用户这句话要触发哪个工具？只能从给定选项中选。",
                {
                    "query_goods": "看商品、问价格、问材质、问有没有货",
                    "add_to_cart": "把某件商品加购、放进购物车、帮我买这个",
                    "checkout": "结算、下单、付款、用优惠券结账",
                    "chitchat": "打招呼、闲聊、与买卖无关的问题",
                    "needs_review": "上面都不贴切，或这句话信息不足以判断",
                },
            ),
        },
        "cases": [
            {"label": "明确指令", "state": "帮我把那副 199 的银耳环放进购物车，明天要送人"},
            {"label": "含糊提问", "state": "那副耳环怎么样"},
        ],
        "decide": decide_intent,
    },
    {
        "id": "catalog",
        "title": "② 类目选择：让 category_id 幻觉变成不可能事件",
        "why": "选项来自数据库，模型能选错，但选不出一个不存在的 ID",
        "questions": {
            "cid": C.choice_q(
                "这条购物需求指向目录里的哪个类目？只能从给定选项中选。",
                CATALOG,
            ),
        },
        "cases": [
            {"label": "指向明确", "state": "想看看有没有适合跑步戴的耳钉，不要太重的"},
            {"label": "跨类目", "state": "想要一套能配裙子的，项链戒指都可以"},
        ],
        "decide": decide_catalog,
    },
    {
        "id": "gate",
        "title": "③ 加购闸门：同一句 Noul，两个输入两种结论",
        "why": "问的不是「要不要执行」，而是「这次执行是否安全」",
        "questions": {
            "safe": C.noul_q(
                "这次加购是用户明确要求、商品与数量都合理，不需要人工确认",
                true_meaning="用户明确要求 加购 一件",
                false_meaning="三件 多件 数量异常 单价很高",
            ),
        },
        "cases": [
            {"label": "正常加购", "state": "把那副 199 的银耳环加购 一件"},
            {"label": "异常加购", "state": "把那条 1899 的金项链加购 三件，多件一起下单"},
        ],
        "decide": decide_gate,
    },
    {
        "id": "triage",
        "title": "④ 一次两问：紧急度（Score）+ 是否退款（Noul）",
        "why": "同一段文本上的多个判断，不该拆成两次请求",
        "questions": {
            "urgency": C.score_q(
                "这条请求有多紧急？按影响排，不看客户情绪。",
                ["可以等一周", "本周内处理", "今天必须回复"],
            ),
            "refund": C.noul_q(
                "客户在要求退款吗？",
                true_meaning="退款 退货 退钱 冲正",
                false_meaning="只是咨询 维修 换货",
            ),
        },
        "cases": [
            {"label": "断链+赶时间", "state": "这条项链昨天就断了，明天我要戴着参加婚礼，现在必须给我解决"},
            {"label": "普通咨询", "state": "想问下这个戒指能不能改圈号，多少钱"},
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
