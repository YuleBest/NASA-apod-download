"""
organize.py — 将 data/ 中的每日 JSON 按月合并，写入 dist/ 目录
- 删除无用字段：media_type, service_version
- 跳过仍然失败的记录（explanation 为 null 且含 error_log）
- 输出：dist/YYYY-MM.json，内容为该月所有日期的列表（按日期升序）

用法:
    python organize.py                          # TUI 模式
    python organize.py --no-tui                 # 纯文本模式
    python organize.py --data-dir ./data2       # 指定数据目录
    python organize.py --dist-dir ./output      # 指定输出目录
"""

import argparse
import json
import os
from collections import defaultdict

from config import load as _load_config

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn
from rich.panel import Panel
from rich import box

# --- 配置区（从 config.json 读取，CLI 参数可覆盖）---
_cfg = _load_config()
SAVE_DIR     = _cfg["data_dir"]
DIST_DIR     = _cfg["dist_dir"]
STRIP_FIELDS = {"media_type", "service_version"}
# --------------

console = Console()


def organize(
    no_tui: bool = False,
    data_dir: str = SAVE_DIR,
    dist_dir: str = DIST_DIR,
) -> None:
    _print = print if no_tui else console.print

    os.makedirs(dist_dir, exist_ok=True)

    all_files = sorted(f for f in os.listdir(data_dir) if f.endswith(".json"))

    if not all_files:
        _print(f"{data_dir}/ 目录为空，无需整理。")
        return

    monthly: dict[str, list[dict]] = defaultdict(list)
    skipped = 0
    total = len(all_files)

    if no_tui:
        # ── 纯文本模式 ──────────────────────────────────────
        for i, fname in enumerate(all_files, 1):
            fpath = os.path.join(data_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                print(f"  读取 {fname} 失败: {e}")
                continue

            if data.get("explanation") is None and "error_log" in data:
                skipped += 1
                continue

            for field in STRIP_FIELDS:
                data.pop(field, None)

            date_str = data.get("date", fname[:10])
            monthly[date_str[:7]].append(data)

            if i % 100 == 0 or i == total:
                print(f"  扫描进度: {i}/{total}")
    else:
        # ── TUI 模式 ────────────────────────────────────────
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("扫描数据文件", total=total)

            for fname in all_files:
                fpath = os.path.join(data_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception as e:
                    console.print(f"[red]  读取 {fname} 失败: {e}[/]")
                    progress.advance(task)
                    continue

                if data.get("explanation") is None and "error_log" in data:
                    skipped += 1
                    progress.advance(task)
                    continue

                for field in STRIP_FIELDS:
                    data.pop(field, None)

                date_str = data.get("date", fname[:10])
                monthly[date_str[:7]].append(data)
                progress.advance(task)

    # 写出每月文件
    written = 0
    for month_key in sorted(monthly.keys()):
        entries = sorted(monthly[month_key], key=lambda d: d.get("date", ""))
        out_path = os.path.join(dist_dir, f"{month_key}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        written += 1

    if no_tui:
        print(f"整理完成  月份文件：{written} 个  跳过失败：{skipped} 条  → {dist_dir}/")
    else:
        console.print(
            Panel(
                f"[green]✅ 整理完成[/]\n"
                f"  月份文件：[bold]{written}[/] 个\n"
                f"  跳过失败：[yellow]{skipped}[/] 条\n"
                f"  输出目录：[dim]{dist_dir}/[/]",
                title="organize",
                border_style="green",
                box=box.ROUNDED,
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="NASA APOD 数据整理",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--no-tui", action="store_true", help="禁用 TUI，输出纯文本日志")
    parser.add_argument("--data-dir", default=SAVE_DIR, metavar="DIR", help="原始数据目录")
    parser.add_argument("--dist-dir", default=DIST_DIR, metavar="DIR", help="合并输出目录")
    args = parser.parse_args()
    organize(no_tui=args.no_tui, data_dir=args.data_dir, dist_dir=args.dist_dir)
