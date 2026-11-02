# jev-demo

把 [Jev](https://api.typesafe.ai)（TypeSafe 的 System One 判定模型）的调用链路在本地跑起来：
**state 进去 → 概率分布出来 → 按阈值分成三档动作**。终端可视化 + 单文件 HTML 报告。

配套文章：飞书《Jev 实战：让软件做判定，而不是让模型生成》。

```
python run.py                     # 终端表格
python run.py --html report.html  # 额外导出一份 HTML 报告
python run.py --live              # 真打 api.typesafe.ai（需要 TYPESAFE_API_KEY）
```

只依赖标准库，Python 3.9+。

---

## 为什么用 Python

- **零依赖**：`python run.py` 直接跑，不用建 Maven、不用下 Jackson、不用对齐 JDK 版本。为了看一眼判定结果，不值得先配半小时环境。
- **契约不打折**：请求体就是 `{model, state, questions}` 的真实 JSON，字段名和官方一致。要搬到 Java 时，只换「发 HTTP 的那一层」，其余逻辑原样搬。
- **改一行就能试**：改 `scenarios.py` 里的 state 或阈值，立刻看到分档变化——这是这个 demo 的主要用途。

如果你要的是「能进生产仓库的 Java 代码」，那应该用 `jev4j`（`io.github.maxsumrall.jev4j:jev4j-core`），不是这个。

---

## 跑起来会看到什么

四个场景、八次判定，覆盖三种原语：

| 场景 | 原语 | 想说明什么 |
|---|---|---|
| ① 意图路由 | Choice | 选项就是工具清单；低概率不猜，直接进澄清 |
| ② 类目选择 | Choice（选项来自「数据库」） | 模型能选错类目，但选不出一个不存在的 `category_id` |
| ③ 加购闸门 | Noul | 同一句问题、两个输入，一个自动执行、一个转人工 |
| ④ 一次两问 | Score + Noul | 同一段文本上的多个判断不该拆成两次请求 |

每个用例最后一行是判定：

- `[自动执行]` 概率够高，直接调工具
- `[二次判定 / 复核]` 中间带，问用户一句或走第二道判定
- `[转人工 / 反问]` 概率太低，不猜

阈值写在 `scenarios.py` 的 `decide_*` 函数里（`0.85 / 0.55`、`0.90 / 0.60` 等），改一个数字就能看到整张表重排。

---

## 哪些是真的，哪些是假的

这一点必须先说清楚，否则这个项目会误导人。

| 部分 | 真假 | 说明 |
|---|---|---|
| 请求 / 响应结构 | **真** | 与官方 `POST /v1/systemone` 一致，`--live` 直接可用 |
| 三种原语的语义 | **真** | Choice 有 `probabilities` + `confidence`；Noul 只有 `noul`；Score 有 `score` + `legend` |
| 阈值分档逻辑 | **真** | 这是生产代码里真正该写的那部分 |
| 概率数字 | **假** | 由「选项描述与输入的字面重合度 + 确定性噪声」算出来，不是模型输出 |
| token 用量 | **假** | 按字符数估的，只用来算量级 |

所以：**看链路可以信，看准确率不要信**。

离线实现（`MockJevClient`）的做法很朴素：把选项描述切成 2 字滑窗，数它有多少落在输入文本里，加权归一化，再用输入的 md5 加一点确定性噪声。好处是结果可复现、能写测试；坏处是它不懂语义——把「不要三件」也会识别成「三件」。这正好也是一个提醒：真模型同样会被否定句坑，别指望概率能替你做校验。

---

## 接真实 API

```bash
# Windows PowerShell
$env:TYPESAFE_API_KEY = "你的 key"
python run.py --live
```

`LiveJevClient` 刻意**不做重试**，也不把失败降级成 `false`——`jev4j` 的设计也是这样：判定失败就该抛，不能伪装成「否」，否则所有动作会一起走错分支。生产里要自己决定 failOpen 还是 failClosed。

注意 `model` 默认 `jev-1.13.0`，是 pin 住的版本。`jev-latest` 会漂移，阈值调好之后必须钉死，并把响应里的 `model` 字段打进日志。

---

## 目录结构

```
jev-demo/
├── run.py                 # 入口：参数解析、选择后端、输出
├── jev_demo/
│   ├── client.py          # 契约构造 + MockJevClient / LiveJevClient
│   ├── scenarios.py       # 四个场景：questions + cases + decide
│   └── render.py          # 终端渲染 + HTML 报告
├── tests/
│   └── test_contract.py   # 形状、可复现、八用例分档、阈值边界
└── report.html            # 跑 --html 生成（可删）
```

```bash
python -m unittest discover -s tests -t .    # 9 个测试
```

测试里有一张「金标准」表（`TestBands.EXPECTED`）：八个用例各自应该落在哪一档。以后改阈值或改 mock 权重，落档一变测试就红——避免演示图悄悄变样。

---

## 换成 Java 时改哪里

| 这个 demo | Java 里对应 |
|---|---|
| `client.system_one(req)` | `jev4j`：`jev.evaluate(text, question...)`；或 `RestClient.post().uri("/v1/systemone")` |
| `C.choice_q(...)` / `C.noul_q(...)` / `C.score_q(...)` | `Jev.choice(Enum.class, "...")` / `Jev.noul("...")` / `Jev.score(Enum.class, "...")` |
| `scenarios.py` 的 `decide_*` | 原样搬，这部分和语言无关 |
| `probabilities` 字典手算 | `answers.answer1().acceptedValue()`（阈值在本地判，jev4j 已经做了） |

一个真实的坑：`Evaluation2.map()` 收到的是**答案对象**，不是解包后的值。所以 record 要写成
`record Triage(ChoiceAnswer<Dept> dept, NoulAnswer refund)`，不能写成 `(Dept, boolean)`。

---

## 已知限制

- **不是语义模型**：同义词、否定句、跨句指代都会判错，别拿它评估 Jev 的真实能力。
- **中文分词很粗**：2-gram 会误命中（「银耳环」和「耳环」都会中），选项描述写得越具体越准。
- **概率没校准**：mock 的 0.94 不代表 94% 正确；真模型的概率也必须在自有样本上验一遍，尤其中文。
- **没有超时/重试/并发**：想压测或压成本，要自己加。
- **只演示判定，不演示副作用**：没有真正加购、下单的实现。
