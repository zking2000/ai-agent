from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import typer

from app.config import load_agent_config, load_dotenv, load_runtime_secrets
from app.confluence_client import ConfluenceClient
from app.crawler import ConfluenceCrawler
from app.summarizer import Summarizer, write_output

app = typer.Typer(add_completion=False, help="Confluence AI Agent MVP")


async def _run_agent(
    config_path: str,
    dotenv_path: str,
    output_format: str | None,
    output_file: str | None,
    print_summary: bool,
    insecure: bool,
) -> None:
    load_dotenv(dotenv_path)
    if insecure:
        os.environ["CONFLUENCE_SSL_VERIFY"] = "false"
        os.environ["LLM_SSL_VERIFY"] = "false"
    config = load_agent_config(config_path)
    secrets = load_runtime_secrets()

    if output_format:
        config.output_format = output_format
    if output_file:
        config.output_file = output_file

    client = ConfluenceClient(secrets=secrets)
    try:
        crawler = ConfluenceCrawler(client=client, config=config)
        pages, stats = await crawler.crawl()
        summarizer = Summarizer(config=config, secrets=secrets)
        result = await summarizer.summarize(pages=pages, stats=stats)
        output_path = write_output(
            result=result,
            output_format=config.output_format,
            output_file=config.output_file,
        )
    finally:
        await client.close()

    typer.echo(f"[summary] mode={result.summary_mode}")
    if result.summary_reason:
        typer.echo(f"[summary] reason={result.summary_reason}")

    if print_summary:
        if config.output_format == "json":
            typer.echo(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
        else:
            typer.echo(result.summary_markdown)

    typer.echo(
        f"\n[done] visited={stats.visited} collected={stats.collected} "
        f"out_of_scope={stats.skipped_out_of_scope} permission={stats.skipped_permission} "
        f"error={stats.skipped_error} output={output_path}"
    )


@app.command()
def run(
    config: str = typer.Option("config.example.toml", "--config", "-c", help="TOML 配置文件路径"),
    dotenv: str = typer.Option(".env", "--env-file", help=".env 文件路径"),
    output_format: str | None = typer.Option(None, "--output-format", help="markdown 或 json"),
    output_file: str | None = typer.Option(None, "--output-file", help="输出文件路径"),
    print_summary: bool = typer.Option(True, "--print-summary/--no-print-summary", help="是否打印总结"),
    insecure: bool = typer.Option(False, "--insecure", help="临时关闭 Confluence 和 LLM 的 TLS 证书校验"),
) -> None:
    """运行 Agent。"""
    try:
        asyncio.run(
            _run_agent(
                config_path=config,
                dotenv_path=dotenv,
                output_format=output_format,
                output_file=output_file,
                print_summary=print_summary,
                insecure=insecure,
            )
        )
    except KeyboardInterrupt:
        typer.echo("已中断。", err=True)
        raise typer.Exit(code=130)
    except Exception as exc:
        typer.echo(f"运行失败: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command("print-structure")
def print_structure() -> None:
    """打印项目目录结构。"""
    root = Path.cwd()
    for path in sorted(root.rglob("*")):
        if ".git" in path.parts or "__pycache__" in path.parts:
            continue
        typer.echo(path.relative_to(root))


if __name__ == "__main__":
    app()
