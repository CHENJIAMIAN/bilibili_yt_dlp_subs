# GAMES101 字幕详尽笔记

本仓库整理了 GAMES101 现代计算机图形学入门课程的中文字幕分片，以及基于每个分片生成的中文结构化详尽笔记。

## 内容

- 根目录：45 个 Markdown 笔记文件，每个文件对应一个字幕分片。
- `源/`：45 个 `.srt` 源字幕文件。
- `summarize_chunks.py`：批量读取 `.srt` 并调用 OpenAI 兼容接口生成笔记的脚本。

## 脚本使用

脚本默认读取当前目录下的 `.srt` 文件，输出到 `summaries/`：

```powershell
$env:CERABRAS_API_KEY='你的 key'
python summarize_chunks.py
```

也可以在本地创建 `.env.local`：

```env
CERABRAS_API_KEY=你的 key
```

`.env.local` 已加入 `.gitignore`，不会提交到仓库。

常用参数：

```powershell
python summarize_chunks.py --dry-run
python summarize_chunks.py --limit 1 --concurrency 1
python summarize_chunks.py --force
```

## 说明

笔记由模型根据字幕内容生成，适合作为课程复习、检索和知识点梳理材料。源字幕保留在 `源/` 目录，便于后续重新生成或校对。
