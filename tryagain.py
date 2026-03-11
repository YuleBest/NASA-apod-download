"""
tryagain.py — 重新下载 data/ 目录中请求失败的日期
判定条件：JSON 文件中 explanation 为 null 且存在 error_log 字段

用法:
    python tryagain.py                     # TUI 模式
    python tryagain.py --no-tui            # 纯文本模式
    python tryagain.py --workers 8         # 并发线程数
    python tryagain.py --data-dir ./data2  # 数据目录
"""

import argparse
import requests
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

from config import load as _load_config

from rich.console import Console
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.progress import (
    Progress,
    BarColumn,
    TaskProgressColumn,
    TimeRemainingColumn,
    SpinnerColumn,
    TextColumn,
    MofNCompleteColumn,
)
from rich.table import Table
from rich.text import Text
from rich import box

# --- 配置区（从 config.json 读取，CLI 参数可覆盖）---
_cfg = _load_config()

def _load_api_key(path: str | None = None) -> str:
    path = path or _cfg["api_key_file"]
    try:
        with open(path, "r", encoding="utf-8") as f:
            key = f.read().strip()
        if not key:
            raise ValueError(f"{path} 为空")
        return key
    except FileNotFoundError:
        raise FileNotFoundError(
            f"找不到 {path}，请先创建该文件并写入你的 NASA API Key。"
        )

API_KEY     = _load_api_key()
SAVE_DIR    = _cfg["data_dir"]
MAX_WORKERS = _cfg["workers"]
# --------------

console = Console()


# ── 扫描失败文件 ──────────────────────────────────────────────
def find_failed_dates(save_dir: str) -> list[str]:
    failed = []
    for fname in sorted(os.listdir(save_dir)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(save_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("explanation") is None and "error_log" in data:
                failed.append(data["date"])
        except Exception:
            pass  # 损坏文件跳过
    return failed


# ── 统计 ──────────────────────────────────────────────────────
class Stats:
    def __init__(self):
        self.lock = Lock()
        self.success = 0
        self.no_data = 0   # NASA 官方本来就没有该日期数据
        self.failed = 0
        self.logs: list[tuple[str, str]] = []

    def add_log(self, style: str, message: str):
        with self.lock:
            self.logs.append((style, message))
            if len(self.logs) > 200:
                self.logs.pop(0)

    def inc(self, key: str):
        with self.lock:
            setattr(self, key, getattr(self, key) + 1)


# ── Rich 面板 ─────────────────────────────────────────────────
def make_stats_panel(stats: Stats, total: int) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan", justify="right")
    table.add_column()
    table.add_row("待重试", str(total))
    table.add_row("✅ 成功", f"[green]{stats.success}[/]")
    table.add_row("🔸 无数据", f"[yellow]{stats.no_data}[/]")
    table.add_row("❌ 失败", f"[red]{stats.failed}[/]")
    return Panel(table, title="[bold]统计", border_style="cyan", box=box.ROUNDED)


def make_log_panel(stats: Stats, height: int = 20) -> Panel:
    text = Text()
    for style, msg in stats.logs[-(height - 2):]:
        text.append(msg + "\n", style=style)
    return Panel(text, title="[bold]日志", border_style="blue", box=box.ROUNDED)


def make_layout(progress: Progress, stats: Stats, total: int, round_num: int = 0) -> Layout:
    title = f"[bold]重试 Round {round_num}" if round_num else "[bold]NASA APOD 重试下载"
    layout = Layout()
    layout.split_column(
        Layout(name="progress", size=3),
        Layout(name="body"),
    )
    layout["body"].split_row(
        Layout(name="stats", ratio=1),
        Layout(name="logs", ratio=3),
    )
    layout["progress"].update(
        Panel(progress, title=title, border_style="magenta", box=box.ROUNDED)
    )
    layout["stats"].update(make_stats_panel(stats, total))
    layout["logs"].update(make_log_panel(stats))
    return layout


# ── 单日下载 ──────────────────────────────────────────────────
def retry_day(date_str: str, stats: Stats) -> None:
    file_path = os.path.join(SAVE_DIR, f"{date_str}.json")
    url = f"https://api.nasa.gov/planetary/apod?api_key={API_KEY}&date={date_str}"

    try:
        response = requests.get(url, timeout=20)

        if response.status_code == 200:
            data = response.json()
            stats.inc("success")
            stats.add_log("green", f"[+] {date_str}  抓取成功")
        else:
            stats.inc("no_data")
            stats.add_log("yellow", f"[~] {date_str}  官方无数据 (HTTP {response.status_code})")
            data = {
                "date": date_str,
                "explanation": None,
                "hdurl": None,
                "media_type": None,
                "title": None,
                "url": None,
                "no_data": True,
                "http_status": response.status_code,
            }

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    except Exception as e:
        stats.inc("failed")
        stats.add_log("red", f"[X] {date_str}  仍然失败: {e}")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                old = json.load(f)
        except Exception:
            old = {"date": date_str, "explanation": None}
        old["error_log"] = str(e)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(old, f, ensure_ascii=False, indent=2)


# ── 执行一轮重试（供 main.py 复用） ──────────────────────────
def run_retry_round(
    round_num: int,
    no_tui: bool = False,
    workers: int = MAX_WORKERS,
    data_dir: str = SAVE_DIR,
) -> int:
    """执行一轮重试，返回仍然失败的数量。"""
    dates = find_failed_dates(data_dir)
    if not dates:
        return 0

    total = len(dates)
    _print = print if no_tui else console.print
    _print(f"第 {round_num} 轮重试，共 {total} 个失败文件...")
    stats = Stats()

    if no_tui:
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(retry_day, d, stats): d for d in dates}
            for future in as_completed(futures):
                future.result()
                done += 1
                if stats.logs:
                    _, msg = stats.logs[-1]
                    print(f"  [{done}/{total}] {msg}")
        print(
            f"  Round {round_num} 结果：成功 {stats.success}  无数据 {stats.no_data}  仍失败 {stats.failed}"
        )
    else:
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
        task_id = progress.add_task(f"重试 Round {round_num}", total=total)
        layout = make_layout(progress, stats, total, round_num)

        with Live(layout, console=console, refresh_per_second=10, screen=True):
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(retry_day, d, stats): d for d in dates}
                for future in as_completed(futures):
                    future.result()
                    progress.advance(task_id)
                    layout["stats"].update(make_stats_panel(stats, total))
                    layout["logs"].update(make_log_panel(stats))

        console.print(
            f"  Round {round_num} 结果：成功 [green]{stats.success}[/]  "
            f"无数据 [yellow]{stats.no_data}[/]  仍失败 [red]{stats.failed}[/]"
        )

    return stats.failed


# ── 主函数 ────────────────────────────────────────────────────
def main(
    no_tui: bool = False,
    workers: int = MAX_WORKERS,
    data_dir: str = SAVE_DIR,
) -> None:
    global SAVE_DIR, MAX_WORKERS
    SAVE_DIR = data_dir
    MAX_WORKERS = workers

    _print = print if no_tui else console.print
    _print(f"正在扫描失败文件（{data_dir}/）...")
    dates = find_failed_dates(SAVE_DIR)
    total = len(dates)

    if total == 0:
        _print("没有需要重试的文件！")
        return

    _print(f"共找到 {total} 个失败日期，开始重试...  线程数 {workers}")
    stats = Stats()

    if no_tui:
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(retry_day, d, stats): d for d in dates}
            for future in as_completed(futures):
                future.result()
                done += 1
                if stats.logs:
                    _, msg = stats.logs[-1]
                    print(f"[{done}/{total}] {msg}")
        print(
            f"重试完成！  成功 {stats.success}  无数据 {stats.no_data}  仍失败 {stats.failed}"
        )
        if stats.failed:
            print("（仍失败的文件保留了 error_log，可再次运行本脚本重试）")
    else:
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
        task_id = progress.add_task("重试下载", total=total)
        layout = make_layout(progress, stats, total)

        with Live(layout, console=console, refresh_per_second=10, screen=True):
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(retry_day, d, stats): d for d in dates}
                for future in as_completed(futures):
                    future.result()
                    progress.advance(task_id)
                    layout["stats"].update(make_stats_panel(stats, total))
                    layout["logs"].update(make_log_panel(stats))

        console.print(
            f"\n[bold green]✅ 重试完成！[/]  成功 [green]{stats.success}[/]  "
            f"无数据 [yellow]{stats.no_data}[/]  仍失败 [red]{stats.failed}[/]"
        )
        if stats.failed:
            console.print("[dim]（仍失败的文件保留了 error_log，可再次运行本脚本重试）[/]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="NASA APOD 失败重试",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--no-tui", action="store_true", help="禁用 TUI，输出纯文本日志")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS, metavar="N", help="并发下载线程数")
    parser.add_argument("--data-dir", default=SAVE_DIR, metavar="DIR", help="原始数据目录")
    args = parser.parse_args()
    main(no_tui=args.no_tui, workers=args.workers, data_dir=args.data_dir)
