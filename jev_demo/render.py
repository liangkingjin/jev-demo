"""终端渲染 + 单文件 HTML 报告。"""

from __future__ import annotations

import html
import time
import unicodedata

BAND = {
    "auto": ("自动执行", "green"),
    "review": ("二次判定 / 复核", "yellow"),
    "human": ("转人工 / 反问", "red"),
}

ANSI = {
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "cyan": "\033[36m",
    "dim": "\033[2m",
    "bold": "\033[1m",
    "reset": "\033[0m",
}

WIDTH = 76


# ---------------------------------------------------------------- 小工具

def dwidth(s):
    """中文算两列，用来对齐。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s, width):
    return s + " " * max(0, width - dwidth(s))


def clip(s, width):
    out, used = "", 0
    for c in s:
        w = 2 if unicodedata.east_asian_width(c) in "WF" else 1
        if used + w > width:
            return out + "…"
        out += c
        used += w
    return out


def wrap(s, width):
    lines, cur, used = [], "", 0
    for c in s:
        w = 2 if unicodedata.east_asian_width(c) in "WF" else 1
        if used + w > width:
            lines.append(cur)
            cur, used = "", 0
        cur += c
        used += w
    if cur:
        lines.append(cur)
    return lines or [""]


def bar(p, width=22, ch="█", empty="░"):
    n = int(round(max(0.0, min(1.0, p)) * width))
    return ch * n + empty * (width - n)


def headline(ans):
    """一句话概括答案，用于汇总表。"""
    t = ans["type"]
    if t == "choice":
        return f"{ans['choice']} {ans['probabilities'][ans['choice']]:.2f}"
    if t == "noul":
        return f"P={ans['noul']:.2f}"
    return f"score={ans['score']:.2f}"


def primary_answer(answers):
    """取第一个问题作为「首选」列。"""
    return next(iter(answers.values()))


def _c(color, s, enable):
    return f"{ANSI[color]}{s}{ANSI['reset']}" if enable else s


# ---------------------------------------------------------------- 终端

def console(results, backend="MOCK", banner="", model="", color=True, tokens=0):
    lines = []
    add = lines.append

    add(_c("bold", "Jev Demo · System One 判定模型", color))
    add(f"backend = {backend}   {banner}")
    add(f"model   = {model}")
    add("═" * WIDTH)

    for sc in results:
        add("")
        add(_c("bold", f"{sc['title']}", color))
        add(_c("dim", f"  {sc['why']}", color))

        for case in sc["cases"]:
            add("")
            add(f"  ┌ {_c('bold', case['label'], color)}")
            for i, line in enumerate(wrap(case["state"], WIDTH - 12)):
                add(f"  │ state: {line}" if i == 0 else f"  │        {line}")
            add("  │")

            for qname, ans in case["answers"].items():
                qtype = ans["type"]
                add(f"  │ {qname}  ({qtype})")
                if qtype == "choice":
                    for opt, p in ans["probabilities"].items():
                        mark = "◀" if opt == ans["choice"] else " "
                        add(f"  │   {pad(clip(opt, 16), 16)} {bar(p)} {p:.2f} {mark}")
                    add(f"  │   → choice={_c('cyan', ans['choice'], color)}   confidence={ans['confidence']:.2f}")
                elif qtype == "noul":
                    p = ans["noul"]
                    add(f"  │   {bar(p)} {p:.2f}")
                    add(f"  │   → noul={_c('cyan', f'{p:.2f}', color)}  （该陈述为真的概率）")
                else:
                    for lvl, p in ans["probabilities"].items():
                        add(f"  │   {lvl} {pad(clip(ans['legend'][lvl], 14), 14)} {bar(p)} {p:.2f}")
                    score_txt = _c("cyan", f"{ans['score']:.2f}", color)
                    add(f"  │   → score={score_txt}   confidence={ans['confidence']:.2f}")
                add("  │")

            label, tone = BAND[case["band"]]
            add(f"  └ 判定 [{_c(tone, label, color)}] {case['action']}")

    add("")
    add("═" * WIDTH)
    add(_c("bold", "汇总", color))
    header = f"  {pad('场景', 30)}{pad('首选', 20)}{'决策'}"
    add(header)

    for sc in results:
        short = sc["title"].split("：")[0]
        for case in sc["cases"]:
            label, tone = BAND[case["band"]]
            name = f"{short} · {case['label']}"
            add(f"  {pad(clip(name, 29), 30)}{pad(headline(primary_answer(case['answers'])), 20)}"
                f"{_c(tone, label, color)}")

    if tokens:
        add("")
        add(_c("dim", f"  本轮共 {tokens} 输入 token；按 jev-1.13 的 0.042 美元/百万输入 token 计，约 "
                     f"${tokens * 0.042 / 1_000_000:.6f}（≈{tokens * 0.042 / 1_000_000 * 7.2:.5f} 元）", color))
    add("")
    return "\n".join(lines)


# ---------------------------------------------------------------- HTML

CSS = """
:root{--ink:#1F2329;--sub:#646A73;--line:#E4E6EB;--soft:#F7F8FA;--blue:#3370FF;
--green:#2EA121;--yellow:#DE7802;--red:#D83931}
*{box-sizing:border-box}
body{margin:0;padding:40px 20px;background:#F5F6F7;color:var(--ink);
font-family:-apple-system,"Segoe UI","Microsoft YaHei",system-ui,sans-serif;line-height:1.6}
.wrap{max-width:960px;margin:0 auto}
h1{font-size:26px;margin:0 0 6px}
.meta{color:var(--sub);font-size:13px;margin-bottom:8px}
.warn{background:#FFF8E6;border:1px solid #F6D3A4;color:#8a5a00;border-radius:8px;
padding:10px 14px;font-size:13px;margin:14px 0 26px}
.card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:22px 24px;margin-bottom:20px}
.card h2{font-size:17px;margin:0 0 4px}
.why{color:var(--sub);font-size:13px;margin-bottom:18px}
.case{border-top:1px dashed var(--line);padding-top:16px;margin-top:16px}
.case:first-of-type{border-top:0;padding-top:0;margin-top:0}
.tag{display:inline-block;background:var(--soft);border:1px solid var(--line);border-radius:20px;
padding:1px 10px;font-size:12px;color:var(--sub);margin-bottom:8px}
.state{background:var(--soft);border-left:3px solid #C9D3E3;border-radius:6px;padding:10px 14px;
font-size:14px;margin-bottom:14px;white-space:pre-wrap}
.qname{font-size:13px;color:var(--sub);margin:14px 0 6px;font-family:ui-monospace,Consolas,monospace}
.row{display:flex;align-items:center;gap:10px;font-size:13px;margin:4px 0}
.opt{width:150px;color:var(--ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.opt.mono{font-family:ui-monospace,Consolas,monospace}
.track{flex:1;height:10px;background:#EEF0F3;border-radius:6px;overflow:hidden}
.fill{height:100%;border-radius:6px;background:#8FA8D8}
.fill.win{background:var(--blue)}
.val{width:52px;text-align:right;color:var(--sub);font-variant-numeric:tabular-nums}
.res{font-family:ui-monospace,Consolas,monospace;font-size:12px;color:var(--blue);margin-top:8px}
.dec{display:flex;align-items:center;gap:10px;margin-top:16px}
.badge{border-radius:6px;padding:3px 10px;font-size:13px;font-weight:600}
.b-auto{background:#EAF7EA;color:var(--green);border:1px solid #B9E2BA}
.b-review{background:#FFF4E3;color:var(--yellow);border:1px solid #F6D3A4}
.b-human{background:#FDECEA;color:var(--red);border:1px solid #F7C5C1}
.act{font-size:14px}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line)}
th{color:var(--sub);font-weight:500;font-size:13px}
td.mono{font-family:ui-monospace,Consolas,monospace;font-size:13px}
footer{color:var(--sub);font-size:12px;text-align:center;margin-top:26px}
"""


def _rows(ans):
    """把一个答案渲染成若干行 (标签, 概率, 是否胜出)。"""
    if ans["type"] == "choice":
        return [(k, v, k == ans["choice"]) for k, v in ans["probabilities"].items()]
    if ans["type"] == "score":
        return [(f"{k} {ans['legend'][k]}", v, False) for k, v in ans["probabilities"].items()]
    return [("P(为真)", ans["noul"], True)]


def html_report(results, backend, banner, model):
    e = html.escape
    out = [
        "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
        "<title>Jev Demo 报告</title><style>", CSS, "</style></head><body><div class=\"wrap\">",
        "<h1>Jev Demo · 三次判定，四次请求</h1>",
        f"<div class=\"meta\">backend = {e(backend)} ｜ model = {e(model)} ｜ "
        f"生成于 {time.strftime('%Y-%m-%d %H:%M')}</div>",
        f"<div class=\"warn\"><b>这是模拟结果，不是真模型。</b>{e(banner)}。"
        "概率由「选项描述与输入的字面重合度 + 确定性噪声」算出，用于演示链路与阈值分流；"
        "接上 TYPESAFE_API_KEY 后执行 <code>python run.py --live</code>，同一套代码打真接口。</div>",
    ]

    for sc in results:
        out.append("<div class=\"card\">")
        out.append(f"<h2>{e(sc['title'])}</h2>")
        out.append(f"<div class=\"why\">{e(sc['why'])}</div>")
        for case in sc["cases"]:
            out.append("<div class=\"case\">")
            out.append(f"<span class=\"tag\">{e(case['label'])}</span>")
            out.append(f"<div class=\"state\">{e(case['state'])}</div>")
            for qname, ans in case["answers"].items():
                out.append(f"<div class=\"qname\">{e(qname)} · {e(ans['type'])}</div>")
                for label, p, win in _rows(ans):
                    pct = max(0.0, min(1.0, p)) * 100
                    mono = " mono" if ans["type"] == "choice" else ""
                    cls = "fill win" if win else "fill"
                    out.append(
                        f"<div class=\"row\"><div class=\"opt{mono}\">{e(str(label))}</div>"
                        f"<div class=\"track\"><div class=\"{cls}\" style=\"width:{pct:.1f}%\"></div></div>"
                        f"<div class=\"val\">{p:.2f}</div></div>"
                    )
                if ans["type"] == "choice":
                    res = f"choice = {ans['choice']}  ·  confidence = {ans['confidence']:.2f}"
                elif ans["type"] == "noul":
                    res = f"noul = {ans['noul']:.2f}"
                else:
                    res = f"score = {ans['score']:.2f}  ·  confidence = {ans['confidence']:.2f}"
                out.append(f"<div class=\"res\">{e(res)}</div>")
            label, tone = BAND[case["band"]]
            out.append(
                f"<div class=\"dec\"><span class=\"badge b-{case['band']}\">{e(label)}</span>"
                f"<span class=\"act\">{e(case['action'])}</span></div>"
            )
            out.append("</div>")
        out.append("</div>")

    out.append("<div class=\"card\"><h2>汇总</h2><table><tr><th>场景</th><th>首选</th><th>决策</th></tr>")
    for sc in results:
        short = sc["title"].split("：")[0]
        for case in sc["cases"]:
            label, _ = BAND[case["band"]]
            out.append(
                f"<tr><td>{e(short)} · {e(case['label'])}</td>"
                f"<td class=\"mono\">{e(headline(primary_answer(case['answers'])))}</td>"
                f"<td><span class=\"badge b-{case['band']}\">{e(label)}</span></td></tr>"
            )
    out.append("</table></div>")
    out.append("<footer>jev-demo · 只演示判定链路与阈值分流，不包含任何真实商品数据</footer>")
    out.append("</div></body></html>")
    return "".join(out)
