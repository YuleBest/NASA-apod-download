"""
main.py — 流水线入口，按顺序执行：
  1. update.py   — 增量下载新日期
  2. tryagain.py — 重试失败文件（最多 3 轮，直到无失败为止）
  3. organize.py — 按月合并，输出 dist/
"""

import os
import json

from rich.console import Console
from rich.rule import Rule
from rich.panel import Panel
from rich import box

console = Console()

SAVE_DIR = "data"
MAX_RETRY_ROUNDS = 3


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


def step(title: str, color: str = "bold cyan"):
    console.print()
    console.print(Rule(f"[{color}] {title} [/{color}]", style=color))


def main():
    console.print(
        Panel(
            "[bold]NASA APOD 数据流水线[/]\n"
            "[dim]update → tryagain（最多 3 轮）→ organize[/]",
            border_style="magenta",
            box=box.DOUBLE_EDGE,
        )
    )

    # ── 1. 增量更新 ───────────────────────────────────────────
    step("Step 1 / 3  增量更新 update.py")
    from update import update
    update()

    # ── 2. 重试失败文件（最多 3 轮）──────────────────────────
    step("Step 2 / 3  重试失败文件 tryagain.py")
    failed_now = count_failed(SAVE_DIR)

    if failed_now == 0:
        console.print("[green]  没有失败记录，跳过重试。[/]")
    else:
        from tryagain import retry_day, Stats, find_failed_dates
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from rich.live import Live
        from rich.layout import Layout
        from rich.progress import (
            Progress, BarColumn, TaskProgressColumn,
            TimeRemainingColumn, SpinnerColumn, TextColumn, MofNCompleteColumn,
        )

        def run_retry_round(round_num: int):
            dates = find_failed_dates(SAVE_DIR)
            if not dates:
                return 0
            console.print(f"[yellow]  第 {round_num} 轮重试，共 {len(dates)} 个失败文件...[/]")
            stats = Stats()

            progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TaskProgressColumn(),
                TimeRemainingColumn(),
                console=console,
                transient=False,
            )
            task_id = progress.add_task(f"重试 Round {round_num}", total=len(dates))

            # 复用 tryagain 的面板构建
            from tryagain import make_stats_panel, make_log_panel
            layout = Layout()
            layout.split_column(
                Layout(name="progress", size=3),
                Layout(name="body"),
            )
            layout["body"].split_row(
                Layout(name="stats", ratio=1),
                Layout(name="logs", ratio=3),
            )
            from rich.panel import Panel
            from rich import box
            layout["progress"].update(
                Panel(progress, title=f"[bold]重试 Round {round_num}", border_style="magenta", box=box.ROUNDED)
            )
            layout["stats"].update(make_stats_panel(stats, len(dates)))
            layout["logs"].update(make_log_panel(stats))

            with Live(layout, console=console, refresh_per_second=10, screen=True):
                with ThreadPoolExecutor(max_workers=4) as executor:
                    futures = {executor.submit(retry_day, d, stats): d for d in dates}
                    for future in as_completed(futures):
                        future.result()
                        progress.advance(task_id)
                        layout["stats"].update(make_stats_panel(stats, len(dates)))
                        layout["logs"].update(make_log_panel(stats))

            console.print(
                f"  Round {round_num} 结果：成功 [green]{stats.success}[/]  "
                f"无数据 [yellow]{stats.no_data}[/]  仍失败 [red]{stats.failed}[/]"
            )
            return stats.failed

        for rnd in range(1, MAX_RETRY_ROUNDS + 1):
            remaining = run_retry_round(rnd)
            if remaining == 0:
                console.print(f"[green]  第 {rnd} 轮后无剩余失败，停止重试。[/]")
                break
            if rnd == MAX_RETRY_ROUNDS:
                console.print(
                    f"[yellow]  已达最大重试轮数 ({MAX_RETRY_ROUNDS})，"
                    f"仍有 {remaining} 个文件失败，保留 error_log 以便下次重试。[/]"
                )

    # ── 3. 整理输出 ───────────────────────────────────────────
    step("Step 3 / 3  整理数据 organize.py")
    from organize import organize
    organize()

    console.print()
    console.print(
        Panel(
            "[bold green]🎉 流水线全部完成！[/]",
            border_style="green",
            box=box.ROUNDED,
        )
    )


if __name__ == "__main__":
    main()
