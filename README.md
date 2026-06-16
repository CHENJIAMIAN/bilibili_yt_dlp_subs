# GAMES101 字幕详尽笔记

GAMES101 现代计算机图形学入门课程的中文结构化笔记合集。仓库保留了字幕源文件，并提供一个可复用的批处理脚本，用于把 `.srt` 字幕分片转换成详尽中文 Markdown 笔记。

## 仓库内容

| 路径 | 说明 |
| --- | --- |
| `*.md` | 45 个课程笔记文件，位于仓库根目录，按课程集数和分片排序。 |
| `源/` | 45 个 `.srt` 源字幕分片，便于重新生成、校对或二次处理。 |
| `summarize_chunks.py` | OpenAI 兼容接口批量总结脚本，支持并发、断点续跑和失败记录。 |

## 适合做什么

- 快速复习 GAMES101 课程重点。
- 检索图形学概念、公式、管线和算法解释。
- 对照源字幕校对或扩写课程笔记。
- 复用脚本批量处理其它 `.srt` 字幕材料。

## 笔记组织

每份 Markdown 对应一个字幕分片，文件名沿用课程标题和分片编号。例如：

```text
01-GAMES101-现代计算机图形学入门-闫令琪 p01 Lecture 01 Overview of Computer Graphics.ai-zh.part01.md
```

源字幕放在 `源/` 目录下，文件名与笔记一一对应，只是扩展名为 `.srt`。

## 重新生成笔记

脚本默认读取当前目录下的 `.srt`，输出到 `summaries/`。如果要重新处理本仓库的源字幕，可以指定输入目录：

```powershell
$env:CERABRAS_API_KEY='你的 key'
python summarize_chunks.py --input-dir 源 --output-dir summaries
```

也可以在本地创建 `.env.local`：

```env
CERABRAS_API_KEY=你的 key
```

`.env.local` 已加入 `.gitignore`，不会提交到仓库。

常用参数：

```powershell
python summarize_chunks.py --dry-run
python summarize_chunks.py --input-dir 源 --limit 1 --concurrency 1
python summarize_chunks.py --input-dir 源 --output-dir summaries --force
```

## 脚本特性

- 默认 5 并发。
- 已存在 Markdown 时自动跳过，支持断点续跑。
- 对网络错误、`429` 和常见 `5xx` 响应做指数退避重试。
- 按 OpenAI 兼容 `stream: true` SSE 响应解析。
- 最终失败项写入 `_failed.jsonl`，不阻塞其它分片。
- API key 只从环境变量或 `.env.local` 读取，不写入源码。

## 说明

笔记由模型根据字幕内容生成，适合作为学习辅助材料。严肃引用或发布前建议对照 `源/` 中的字幕进行人工校对。
