"""
organize.py — 将 data/ 中的每日 JSON 按月合并，写入 dist/ 目录
- 删除无用字段：media_type, service_version
- 跳过仍然失败的记录（explanation 为 null 且含 error_log）
- 输出：dist/YYYY-MM.json，内容为该月所有日期的列表（按日期升序）
"""

import json
import os
from collections import defaultdict

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn
from rich.panel import Panel
from rich import box

SAVE_DIR = "data"
DIST_DIR = "dist"
STRIP_FIELDS = {"media_type", "service_version"}

console = Console()


def organize():
    if not os.path.exists(DIST_DIR):
        os.makedirs(DIST_DIR)

    all_files = sorted(
        f for f in os.listdir(SAVE_DIR) if f.endswith(".json")
    )

    if not all_files:
        console.print("[yellow]data/ 目录为空，无需整理。[/]")
        return

    monthly: dict[str, list[dict]] = defaultdict(list)
    skipped = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("扫描数据文件", total=len(all_files))

        for fname in all_files:
            fpath = os.path.join(SAVE_DIR, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                console.print(f"[red]  读取 {fname} 失败: {e}[/]")
                progress.advance(task)
                continue

            # 跳过仍然失败的记录
            if data.get("explanation") is None and "error_log" in data:
                skipped += 1
                progress.advance(task)
                continue

            # 去除无用字段
            for field in STRIP_FIELDS:
                data.pop(field, None)

            # 按 YYYY-MM 分组
            date_str = data.get("date", fname[:10])
            month_key = date_str[:7]  # "YYYY-MM"
            monthly[month_key].append(data)
            progress.advance(task)

    # 写出每月文件
    written = 0
    for month_key in sorted(monthly.keys()):
        entries = sorted(monthly[month_key], key=lambda d: d.get("date", ""))
        out_path = os.path.join(DIST_DIR, f"{month_key}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        written += 1

    console.print(
        Panel(
            f"[green]✅ 整理完成[/]\n"
            f"  月份文件：[bold]{written}[/] 个\n"
            f"  跳过失败：[yellow]{skipped}[/] 条",
            title="organize",
            border_style="green",
            box=box.ROUNDED,
        )
    )


if __name__ == "__main__":
    organize()
