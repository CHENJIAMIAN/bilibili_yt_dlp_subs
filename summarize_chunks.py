from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import os
from pathlib import Path
import random
import sys
import time
from typing import Any
from urllib import error, request


API_URL = "https://cerabras.571574085.xyz/v1/chat/completions"
MODEL = "zai-glm-4.7"
PROMPT = """1、请返回您仔细阅读正文后精心写成的详尽笔记
2、用中文分点结构化阐述
3、不要遗漏任何一个有价值的细节"""
RETRY_STATUSES = {429, 500, 502, 503, 504}
USER_AGENT = "bilibili-yt-dlp-subs/1.0"


class RetryableError(Exception):
    pass


class NonRetryableError(Exception):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="批量读取当前目录 .srt 字幕分片并调用 OpenAI 兼容接口生成中文详尽笔记。"
    )
    parser.add_argument("--input-dir", type=Path, default=Path("."), help="字幕所在目录，默认当前目录")
    parser.add_argument("--output-dir", type=Path, default=Path("summaries"), help="输出目录，默认 summaries")
    parser.add_argument("--concurrency", type=int, default=5, help="并发请求数，默认 5")
    parser.add_argument("--max-retries", type=int, default=5, help="单个文件最多尝试次数，默认 5")
    parser.add_argument("--limit", type=int, default=None, help="只处理前 N 个待生成分片")
    parser.add_argument("--dry-run", action="store_true", help="只打印将处理的文件，不发送请求")
    parser.add_argument("--force", action="store_true", help="重新生成已存在的 Markdown")
    parser.add_argument("--timeout", type=int, default=300, help="单次请求超时时间，单位秒，默认 300")
    return parser.parse_args()


def output_path_for(source: Path, output_dir: Path) -> Path:
    return output_dir / source.with_suffix(".md").name


def collect_jobs(input_dir: Path, output_dir: Path, *, limit: int | None, force: bool) -> tuple[list[Path], int]:
    sources = sorted(input_dir.glob("*.srt"), key=lambda p: p.name)
    existing = 0
    jobs: list[Path] = []
    for source in sources:
        target = output_path_for(source, output_dir)
        if target.exists() and not force:
            existing += 1
            continue
        jobs.append(source)
    if limit is not None:
        jobs = jobs[:limit]
    return jobs, existing


def request_summary(api_key: str, subtitle_text: str, *, timeout: int) -> str:
    payload = {
        "model": MODEL,
        "stream": True,
        "messages": [
            {
                "role": "user",
                "content": f"{PROMPT}\n\n{sub_title_block(subtitle_text)}",
            }
        ],
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        API_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://localhost/bilibili-yt-dlp-subs",
            "User-Agent": USER_AGENT,
            "X-Title": "bilibili yt-dlp subtitle summaries",
        },
    )

    chunks: list[str] = []
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            if status in RETRY_STATUSES:
                raise RetryableError(f"HTTP {status}")
            if status >= 400:
                raise NonRetryableError(f"HTTP {status}")

            while True:
                raw_line = resp.readline()
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue

                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError as exc:
                    raise RetryableError(f"SSE JSON 解析失败: {exc}") from exc

                for choice in event.get("choices", []):
                    delta = choice.get("delta") or {}
                    content = delta.get("content")
                    if content:
                        chunks.append(content)
    except error.HTTPError as exc:
        detail = read_error_detail(exc)
        message = f"HTTP {exc.code}: {detail}" if detail else f"HTTP {exc.code}"
        if exc.code in RETRY_STATUSES:
            raise RetryableError(message) from exc
        raise NonRetryableError(message) from exc
    except (TimeoutError, OSError) as exc:
        raise RetryableError(str(exc)) from exc

    summary = "".join(chunks).strip()
    if not summary:
        raise RetryableError("接口返回空内容")
    return summary


def sub_title_block(text: str) -> str:
    return f"下面是字幕分片正文：\n\n{text}"


def read_error_detail(exc: error.HTTPError) -> str:
    try:
        return exc.read(2048).decode("utf-8", errors="replace").strip()
    except Exception:
        return ""


def write_summary(source: Path, target: Path, summary: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    generated_at = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
    content = f"# {source.name}\n\n生成时间：{generated_at}\n\n{summary.strip()}\n"
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(content, encoding="utf-8", newline="\n")
    temp.replace(target)


def summarize_one(source: Path, output_dir: Path, api_key: str, max_retries: int, timeout: int) -> dict[str, Any]:
    target = output_path_for(source, output_dir)
    text = source.read_text(encoding="utf-8-sig")
    started = time.time()
    last_error = ""

    for attempt in range(1, max_retries + 1):
        try:
            summary = request_summary(api_key, text, timeout=timeout)
            write_summary(source, target, summary)
            return {
                "source": source.name,
                "target": str(target),
                "status": "ok",
                "attempts": attempt,
                "seconds": round(time.time() - started, 2),
            }
        except NonRetryableError as exc:
            return {
                "source": source.name,
                "target": str(target),
                "status": "failed",
                "attempts": attempt,
                "error": str(exc),
            }
        except RetryableError as exc:
            last_error = str(exc)
            if attempt < max_retries:
                delay = min(60.0, 2 ** (attempt - 1)) + random.uniform(0.0, 0.8)
                print(f"[重试] {source.name} 第 {attempt}/{max_retries} 次失败：{last_error}，{delay:.1f}s 后重试")
                time.sleep(delay)

    return {
        "source": source.name,
        "target": str(target),
        "status": "failed",
        "attempts": max_retries,
        "error": last_error or "未知错误",
    }


def append_failure(output_dir: Path, result: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    failed_path = output_dir / "_failed.jsonl"
    with failed_path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(result, ensure_ascii=False) + "\n")


def load_api_key() -> str:
    api_key = os.environ.get("CERABRAS_API_KEY", "").strip()
    if api_key:
        return api_key

    env_path = Path(".env.local")
    if not env_path.exists():
        return ""

    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "CERABRAS_API_KEY":
            return value.strip().strip('"').strip("'")
    return ""


def main() -> int:
    configure_console()
    args = parse_args()
    if args.concurrency < 1:
        print("错误：--concurrency 必须大于等于 1", file=sys.stderr)
        return 2
    if args.max_retries < 1:
        print("错误：--max-retries 必须大于等于 1", file=sys.stderr)
        return 2
    if args.limit is not None and args.limit < 1:
        print("错误：--limit 必须大于等于 1", file=sys.stderr)
        return 2

    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()
    jobs, existing = collect_jobs(input_dir, output_dir, limit=args.limit, force=args.force)
    total = len(list(input_dir.glob("*.srt")))

    print(f"输入目录：{input_dir}")
    print(f"输出目录：{output_dir}")
    print(f".srt 总数：{total}")
    print(f"已存在并跳过：{0 if args.force else existing}")
    print(f"将处理：{len(jobs)}")
    print(f"并发数：{args.concurrency}")

    if args.dry_run:
        for source in jobs:
            print(f"DRY-RUN {source.name} -> {output_path_for(source, output_dir).name}")
        return 0

    api_key = load_api_key()
    if not api_key:
        print("错误：缺少 CERABRAS_API_KEY，请先设置环境变量或填写 .env.local。", file=sys.stderr)
        return 2

    if not jobs:
        print("没有需要处理的字幕分片。")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    failed = 0
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {
            executor.submit(summarize_one, source, output_dir, api_key, args.max_retries, args.timeout): source
            for source in jobs
        }
        for future in concurrent.futures.as_completed(futures):
            source = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "source": source.name,
                    "target": str(output_path_for(source, output_dir)),
                    "status": "failed",
                    "attempts": 0,
                    "error": f"未捕获异常: {exc}",
                }

            completed += 1
            if result["status"] == "ok":
                print(f"[完成 {completed}/{len(jobs)}] {result['source']} ({result['seconds']}s)")
            else:
                failed += 1
                append_failure(output_dir, result)
                print(f"[失败 {completed}/{len(jobs)}] {result['source']}：{result['error']}", file=sys.stderr)

    if failed:
        print(f"完成，失败 {failed} 个。详情见 {output_dir / '_failed.jsonl'}", file=sys.stderr)
        return 1

    print("全部完成。")
    return 0


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    raise SystemExit(main())
