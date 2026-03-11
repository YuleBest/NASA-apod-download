"""
main.py — 流水线入口，按顺序执行：
  1. update.py   — 增量下载新日期
  2. tryagain.py — 重试失败文件（最多 3 轮，直到无失败为止）
  3. organize.py — 按月合并，输出 dist/

用法:
    python main.py                          # TUI 模式
    python main.py --no-tui                 # 纯文本模式
    python main.py --workers 8              # 并发线程数
    python main.py --max-retries 5          # 最大重试轮数
    python main.py --data-dir ./data2       # 数据目录
    python main.py --dist-dir ./output      # 输出目录
    python main.py --start 2025-01-01       # 指定增量起始日期
    python main.py --end 2025-06-30         # 指定增量结束日期
"""

import argparse
import os
import json

from config import load as _load_config

from rich.console import Console
from rich.rule import Rule
from rich.panel import Panel
from rich import box

console = Console()

# --- 配置区（从 config.json 读取，CLI 参数可覆盖）---
_cfg = _load_config()
SAVE_DIR         = _cfg["data_dir"]
MAX_RETRY_ROUNDS = _cfg["max_retry_rounds"]
# --------------


def count_failed(save_dir: str) -> int:
    """统计 data/ 中仍然失败的文件数（explanation=null + error_log 存在）"""
    count = 0
    for fname in os.listdir(save_dir):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(save_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("explanation") is None and "error_log" in data:
                count += 1
        except Exception:
            pass
    return count


def step(title: str, no_tui: bool, color: str = "bold cyan") -> None:
    if no_tui:
        print(f"\n{'='*60}")
        print(f"  {title}")
        print(f"{'='*60}")
    else:
        console.print()
        console.print(Rule(f"[{color}] {title} [/{color}]", style=color))


def main(
    no_tui: bool = False,
    workers: int = 4,
    max_retries: int = MAX_RETRY_ROUNDS,
    data_dir: str = SAVE_DIR,
    dist_dir: str = "dist",
    start_date: str | None = None,
    end_date: str | None = None,
) -> None:
    _print = print if no_tui else console.print

    if no_tui:
        print("NASA APOD 数据流水线")
        print(f"update → tryagain（最多 {max_retries} 轮）→ organize")
        if start_date or end_date:
            print(f"日期范围：{start_date or '自动'} → {end_date or '今天'}")
        print(f"数据目录：{data_dir}  输出目录：{dist_dir}  线程数：{workers}")
    else:
        desc = (
            f"[bold]NASA APOD 数据流水线[/]\n"
            f"[dim]update → tryagain（最多 {max_retries} 轮）→ organize[/]"
        )
        if start_date or end_date:
            desc += f"\n[dim]日期范围：{start_date or '自动'} → {end_date or '今天'}[/]"
        desc += f"\n[dim]数据目录：{data_dir}  输出：{dist_dir}  线程数：{workers}[/]"
        console.print(Panel(desc, border_style="magenta", box=box.DOUBLE_EDGE))

    # ── 1. 增量更新 ───────────────────────────────────────────
    step("Step 1 / 3  增量更新 update.py", no_tui)
    from update import update
    update(no_tui=no_tui, start_date=start_date, end_date=end_date,
           workers=workers, data_dir=data_dir)

    # ── 2. 重试失败文件（最多 N 轮）──────────────────────────
    step("Step 2 / 3  重试失败文件 tryagain.py", no_tui)
    failed_now = count_failed(data_dir)

    if failed_now == 0:
        _print("  没有失败记录，跳过重试。")
    else:
        from tryagain import run_retry_round

        for rnd in range(1, max_retries + 1):
            remaining = run_retry_round(rnd, no_tui=no_tui,
                                        workers=workers, data_dir=data_dir)
            if remaining == 0:
                _print(f"  第 {rnd} 轮后无剩余失败，停止重试。")
                break
            if rnd == max_retries:
                _print(
                    f"  已达最大重试轮数 ({max_retries})，"
                    f"仍有 {remaining} 个文件失败，保留 error_log 以便下次重试。"
                )

    # ── 3. 整理输出 ───────────────────────────────────────────
    step("Step 3 / 3  整理数据 organize.py", no_tui)
    from organize import organize
    organize(no_tui=no_tui, data_dir=data_dir, dist_dir=dist_dir)

    if no_tui:
        print("\n流水线全部完成！")
    else:
        console.print()
        console.print(
            Panel(
                "[bold green]🎉 流水线全部完成！[/]",
                border_style="green",
                box=box.ROUNDED,
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="NASA APOD 数据流水线",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--no-tui", action="store_true", help="禁用 TUI，输出纯文本日志")
    parser.add_argument("--workers", type=int, default=4, metavar="N", help="并发下载线程数")
    parser.add_argument("--max-retries", type=int, default=MAX_RETRY_ROUNDS, metavar="N", help="tryagain 最大重试轮数")
    parser.add_argument("--data-dir", default=SAVE_DIR, metavar="DIR", help="原始数据保存目录")
    parser.add_argument("--dist-dir", default="dist", metavar="DIR", help="合并输出目录")
    parser.add_argument("--start", metavar="DATE", help="增量起始日期 YYYY-MM-DD（默认：自动检测）")
    parser.add_argument("--end", metavar="DATE", help="增量结束日期 YYYY-MM-DD（默认：今天）")
    args = parser.parse_args()
    main(
        no_tui=args.no_tui,
        workers=args.workers,
        max_retries=args.max_retries,
        data_dir=args.data_dir,
        dist_dir=args.dist_dir,
        start_date=args.start,
        end_date=args.end,
    )
