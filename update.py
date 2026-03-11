"""
update.py — 增量下载 NASA APOD 数据
- 自动检测 data/ 中已有的最新日期，从第二天开始到今天
- 已存在的文件直接跳过（幂等）
- Rich TUI 与 main.py 风格一致
"""

import requests
import json
import os
from datetime import datetime, timedelta, date
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

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
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text
from rich import box

# --- 配置区 ---
def _load_api_key(path: str = "api-key.txt") -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            key = f.read().strip()
        if not key:
            raise ValueError("api-key.txt 为空")
        return key
    except FileNotFoundError:
        raise FileNotFoundError(
            f"找不到 {path}，请先创建该文件并写入你的 NASA API Key。"
        )

API_KEY = _load_api_key()
SAVE_DIR = "data"
MAX_WORKERS = 4
APOD_START = "1995-06-16"   # NASA APOD 最早日期
API_RATE_LIMIT = 1000        # NASA API 每小时请求上限
# --------------

console = Console()

if not os.path.exists(SAVE_DIR):
    os.makedirs(SAVE_DIR)


# ── 日期工具 ──────────────────────────────────────────────────
def latest_existing_date(save_dir: str) -> str | None:
    """返回 data/ 中文件名最大的日期字符串，或 None"""
    dates = []
    for fname in os.listdir(save_dir):
        if fname.endswith(".json") and len(fname) == 15:  # YYYY-MM-DD.json
            dates.append(fname[:10])
    return max(dates) if dates else None


def get_date_range() -> list[str]:
    """从最新已有日期的下一天到今天"""
    today = date.today().isoformat()
    latest = latest_existing_date(SAVE_DIR)

    if latest is None:
        start_str = APOD_START
    else:
        start_dt = datetime.strptime(latest, "%Y-%m-%d") + timedelta(days=1)
        start_str = start_dt.strftime("%Y-%m-%d")

    if start_str > today:
        return []

    result = []
    curr = datetime.strptime(start_str, "%Y-%m-%d")
    end = datetime.strptime(today, "%Y-%m-%d")
    while curr <= end:
        result.append(curr.strftime("%Y-%m-%d"))
        curr += timedelta(days=1)
    return result


# ── 统计 ──────────────────────────────────────────────────────
class Stats:
    def __init__(self):
        self.lock = Lock()
        self.success = 0
        self.skipped = 0
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
    table.add_row("新增日期", str(total))
    table.add_row("✅ 成功", f"[green]{stats.success}[/]")
    table.add_row("⏭  跳过", f"[dim]{stats.skipped}[/]")
    table.add_row("❌ 失败", f"[red]{stats.failed}[/]")
    return Panel(table, title="[bold]统计", border_style="cyan", box=box.ROUNDED)


def make_log_panel(stats: Stats, height: int = 20) -> Panel:
    text = Text()
    for style, msg in stats.logs[-(height - 2):]:
        text.append(msg + "\n", style=style)
    return Panel(text, title="[bold]日志", border_style="blue", box=box.ROUNDED)


def make_layout(progress: Progress, stats: Stats, total: int) -> Layout:
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
        Panel(progress, title="[bold]NASA APOD 增量更新", border_style="magenta", box=box.ROUNDED)
    )
    layout["stats"].update(make_stats_panel(stats, total))
    layout["logs"].update(make_log_panel(stats))
    return layout


# ── 单日下载 ──────────────────────────────────────────────────
def download_day(date_str: str, stats: Stats) -> None:
    file_path = os.path.join(SAVE_DIR, f"{date_str}.json")

    if os.path.exists(file_path):
        stats.inc("skipped")
        stats.add_log("dim", f"⏭  {date_str}  已存在，跳过")
        return

    url = f"https://api.nasa.gov/planetary/apod?api_key={API_KEY}&date={date_str}"
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            data = response.json()
            stats.inc("success")
            stats.add_log("green", f"✅ {date_str}  抓取成功")
        else:
            stats.inc("failed")
            stats.add_log("yellow", f"⚠  {date_str}  官方无数据 (HTTP {response.status_code})")
            data = {
                "date": date_str,
                "explanation": None,
                "hdurl": None,
                "media_type": None,
                "title": None,
                "url": None,
                "error_log": f"HTTP {response.status_code}",
            }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        stats.inc("failed")
        stats.add_log("red", f"❌ {date_str}  请求异常: {e}")
        data = {"date": date_str, "explanation": None, "error_log": str(e)}
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


# ── 入口 ──────────────────────────────────────────────────────
def update():
    dates = get_date_range()
    total = len(dates)

    if total == 0:
        console.print("[bold green]✅ 已是最新，无需更新。[/]")
        return

    latest = latest_existing_date(SAVE_DIR) or "（无）"
    today = date.today().isoformat()
    console.print(
        f"[bold cyan]增量更新[/]  "
        f"已有最新：[dim]{latest}[/]  →  今日：[bold]{today}[/]  "
        f"共 [bold]{total}[/] 天"
    )

    # ── API 速率限制警告 ──────────────────────────────────────
    if total > API_RATE_LIMIT:
        console.print(
            Panel(
                f"[bold yellow]⚠  请求数量超过 API 速率限制！[/]\n\n"
                f"  本次需下载 [bold]{total}[/] 天的数据，"
                f"但 NASA API 每小时限制 [bold]{API_RATE_LIMIT}[/] 次请求。\n"
                f"  超出部分会触发 429 错误并被记为失败，可在下次运行时通过 tryagain.py 重试。\n\n"
                f"  [dim]建议分批运行，每次不超过 {API_RATE_LIMIT} 天。[/]",
                title="[bold red]速率限制警告",
                border_style="yellow",
                box=box.ROUNDED,
            )
        )
        if not Confirm.ask(f"仍要一次性下载全部 {total} 天数据吗？", default=False):
            console.print("[dim]已取消，未做任何下载。[/]")
            return

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
    task_id = progress.add_task("下载", total=total)
    layout = make_layout(progress, stats, total)

    with Live(layout, console=console, refresh_per_second=10, screen=True):
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(download_day, d, stats): d for d in dates}
            for future in as_completed(futures):
                future.result()
                progress.advance(task_id)
                layout["stats"].update(make_stats_panel(stats, total))
                layout["logs"].update(make_log_panel(stats))

    console.print(
        f"\n[bold green]✅ 增量更新完成！[/]  "
        f"成功 [green]{stats.success}[/]  "
        f"跳过 [dim]{stats.skipped}[/]  "
        f"失败 [red]{stats.failed}[/]"
    )


if __name__ == "__main__":
    update()
