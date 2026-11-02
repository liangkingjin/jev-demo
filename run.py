#!/usr/bin/env python3
"""jev-demo：离线跑通 Jev 的判定链路。

用法：
    python run.py                    # 离线模拟，终端表格
    python run.py --html out.html    # 顺便导出一份 HTML 报告
    python run.py --live             # 真打 TypeSafe（需 TYPESAFE_API_KEY）
    python run.py --json             # 打印原始响应 JSON，方便对照契约

只依赖标准库。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from jev_demo import client, render, scenarios


def main(argv=None):
    ap = argparse.ArgumentParser(description="Jev 判定模型演示")
    ap.add_argument("--live", action="store_true", help="调用真实 API（需 TYPESAFE_API_KEY）")
    ap.add_argument("--model", default=client.MODEL, help=f"模型版本，默认 {client.MODEL}")
    ap.add_argument("--html", metavar="PATH", help="导出单文件 HTML 报告")
    ap.add_argument("--json", action="store_true", help="打印原始响应 JSON")
    ap.add_argument("--no-color", action="store_true", help="关闭终端颜色")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if args.live:
        if not os.environ.get("TYPESAFE_API_KEY"):
            print("需要先设置环境变量 TYPESAFE_API_KEY（去 TypeSafe 申请 key 后）", file=sys.stderr)
            return 2
        cli = client.LiveJevClient(model=args.model)
    else:
        cli = client.MockJevClient(model=args.model)

    results = scenarios.run_all(cli)
    tokens = sum(c["usage"].get("input_tokens", 0) for sc in results for c in sc["cases"])

    color = (not args.no_color) and sys.stdout.isatty()
    print(render.console(results, cli.name, cli.banner, cli.model, color=color, tokens=tokens))

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))

    if args.html:
        path = os.path.abspath(args.html)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(render.html_report(results, cli.name, cli.banner, cli.model))
        print(f"HTML 报告已写入 {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
