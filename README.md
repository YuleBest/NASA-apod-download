# NASA APOD Downloader

批量下载 [NASA 每日天文图片（APOD）](https://apod.nasa.gov/) 数据，支持增量更新、失败重试，并按月整理输出。

## 项目结构

```
NASA-apod-downloader/
├── api-key.txt      # ⚠️ 你的 NASA API Key
├── main.py          # 流水线入口：update → tryagain → organize
├── update.py        # 增量下载（自动检测最新日期，按天下载到今日）
├── tryagain.py      # 重试失败记录（explanation=null 且含 error_log）
├── organize.py      # 按月合并数据，输出到 dist/
├── data/            # 每日原始 JSON
└── dist/            # 按月合并的 JSON（如 2024-03.json）
```

## 快速开始

### 1. 获取 API Key

前往 [https://api.nasa.gov/](https://api.nasa.gov/) 免费申请，填写邮箱即可获得。

> **速率限制**：NASA API 每小时最多 **1000 次**请求。`update.py` 会在请求数超过 1000 时弹出警告并询问是否继续；超出部分会被记为失败，可通过 `tryagain.py` 在下一小时重试。建议每次运行不超过 1000 天范围。

### 2. 配置 Key

将 Key 写入项目根目录的 `api-key.txt`：

```
YOUR_NASA_API_KEY_HERE
```

> ⚠️ 该文件已被 `.gitignore` 排除，不会提交到仓库。

### 3. 安装依赖

项目使用 [uv](https://github.com/astral-sh/uv) 管理依赖：

```bash
uv sync
```

### 4. 运行

```bash
# 完整流水线（推荐，每次执行时使用）
uv run python main.py

# 单独运行各步骤
uv run python update.py      # 仅增量下载
uv run python tryagain.py    # 仅重试失败
uv run python organize.py    # 仅整理输出
```

## 输出格式

`dist/YYYY-MM.json` 为该月所有日期的数据数组，每条记录结构如下：

```jsonc
[
  {
    "copyright": "...", // 版权（可选）
    "date": "2024-03-01",
    "explanation": "...", // 图片说明
    "hdurl": "https://...", // 高清图片链接
    "title": "...", // 标题
    "url": "https://...", // 标准图片 / 视频链接
  },
]
```

> `media_type` 和 `service_version` 字段在整理阶段会被自动删除。

## 流水线说明

```
main.py
 ├─ update.py    检测 data/ 中最新日期，下载次日至今日的数据
 ├─ tryagain.py  重试超时/网络错误记录，最多 3 轮，零失败时提前停止
 └─ organize.py  读取 data/，按月分组写入 dist/，跳过仍失败的记录
```

## 依赖

| 包         | 用途                         |
| ---------- | ---------------------------- |
| `requests` | HTTP 请求                    |
| `rich`     | 终端 TUI（进度条、日志面板） |

## LICENSE

MIT
