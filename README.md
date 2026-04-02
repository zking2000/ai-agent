# Confluence AI Agent MVP

一个可运行的 Python 3.11 Agent，用于在受控范围内读取 Confluence 页面，递归抓取相关内容，过滤不属于当前 project/topic 的链接，并输出简洁总结。

## 功能

- 优先使用 Confluence REST API
- 支持 HTML 抓取模式作为回退
- 支持递归遍历子页面和页面内链接
- 支持基于 `space + parent page + URL path` 的 scope guard
- 支持页面抽取与正文清洗
- 支持 LLM 总结，失败时自动回退到本地摘要
- 支持输出 `markdown` 或 `json`
- 适合通过 `python -m app.main`、`confluence-agent`、`opencode run` 等方式调用

## 项目结构

```text
.
├── .env.example
├── config.example.toml
├── pyproject.toml
├── README.md
├── requirements.txt
└── app
    ├── __init__.py
    ├── config.py
    ├── confluence_client.py
    ├── crawler.py
    ├── extractor.py
    ├── main.py
    ├── models.py
    ├── scope_guard.py
    └── summarizer.py
```

## 安装

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

或：

```bash
pip install -e .
```

## 配置

1. 复制环境变量文件：

```bash
cp .env.example .env
```

2. 填写 `.env`：

- `CONFLUENCE_BASE_URL`: 例如 `https://confluence.example.com/wiki`
- `CONFLUENCE_EMAIL` + `CONFLUENCE_API_TOKEN`: 推荐的 Confluence REST API 鉴权方式
- `CONFLUENCE_BEARER_TOKEN`: 如果你用 Bearer Token，可替代上面的 Basic Auth
- `HTML_COOKIE`: HTML 抓取模式下如果需要登录态，可填 Cookie
- `CONFLUENCE_SSL_VERIFY`: 默认为 `true`，内网自签证书场景可临时设为 `false`
- `CONFLUENCE_CA_BUNDLE`: 自定义 CA 证书文件路径，优先于 `CONFLUENCE_SSL_VERIFY`
- `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`: OpenAI 兼容接口配置
- `LLM_SSL_VERIFY` / `LLM_CA_BUNDLE`: 模型网关的 TLS 校验配置

3. 复制配置文件：

```bash
cp config.example.toml config.toml
```

4. 修改 `config.toml`：

- `mode = "api"`：优先推荐
- `start_page_id`：起始页面 ID
- `start_url`：HTML 模式或补充入口
- `answer_language`：总结输出语言，默认 `zh-CN`
- `scope.allowed_space`：限制空间
- `scope.allowed_parent_page_id`：限制父页面边界
- `scope.allowed_url_prefixes`：限制 URL path 前缀
- `llm.api_style`：`auto`、`responses` 或 `chat_completions`

## 运行

API 模式：

```bash
python -m app.main run --config config.toml
```

如果你抓的是英文页面，但想用中文回答，请在 `config.toml` 里设置：

```toml
answer_language = "zh-CN"
```

如果是内网自签证书环境，也可以临时跳过 TLS 校验：

```bash
python -m app.main run --config config.toml --insecure
```

HTML 模式：

```bash
python -m app.main run --config config.toml --output-format markdown
```

安装脚本后也可以：

```bash
confluence-agent run --config config.toml
```

只写文件不打印总结：

```bash
python -m app.main run --config config.toml --no-print-summary
```

运行时会额外打印摘要方式，例如 `mode=llm` 或 `mode=fallback`，方便判断这次是否真的调用了模型。

输出 JSON：

```bash
python -m app.main run --config config.toml --output-format json --output-file output/result.json
```

## MVP 行为说明

### API 模式

- 根据 `start_page_id` 拉取页面正文
- 递归拉取子页面
- 额外解析正文中的页面链接并尝试继续遍历
- 对于 `401/403/404` 页面会优雅跳过，不中断整个任务

### HTML 模式

- 根据 `start_url` 抓取 HTML
- 提取正文和链接
- 仅继续遍历同域链接
- 结合 scope guard 拒绝无关页面

### Scope Guard

优先基于以下条件过滤：

- `allowed_space`
- `allowed_parent_page_id`
- `allowed_url_prefixes`

任何条件不满足时，该页面会被判定为超出范围并跳过。

## 输出

### Markdown

默认输出简洁结论：

- `结论`
- `关键点`
- `行动项`
- `来源页面`

### JSON

包含：

- 抓取到的页面内容
- crawl 统计信息
- markdown 摘要

## 用于 opencode / agent 的建议调用方式

```bash
python -m app.main run --config config.toml --output-format json --output-file output/result.json --no-print-summary
```

这样外层 agent 可以直接消费结构化结果。

如果你通过本地 `opencode` 网关调用模型，建议在 `config.toml` 中设置：

```toml
[llm]
enabled = true
api_style = "auto"
```

`auto` 会优先尝试 `responses` API，再回退到 `chat/completions`，更适合不同模型和本地代理网关的差异。
当前实现还会对同一接口尝试多种请求体格式，并在必要时去掉 `temperature`，以兼容不同代理对 OpenAI 风格请求的差异。

## 注意事项

- Confluence Cloud 一般优先使用 `email + api token`
- 如果页面权限不足，程序会跳过该页面并继续执行
- HTML 模式下，若页面依赖登录态，请提供 `HTML_COOKIE`
- LLM 配置缺失或调用失败时，会自动降级为本地摘要，确保 MVP 可运行

## 证书问题排查

如果运行时报 `certificate verify failed`，通常是目标站点或模型网关使用了自签 CA。

优先推荐：

```bash
CONFLUENCE_CA_BUNDLE=/path/to/custom-ca.pem
LLM_CA_BUNDLE=/path/to/custom-ca.pem
```

如果只是临时验证链路，也可以关闭校验：

```bash
CONFLUENCE_SSL_VERIFY=false
LLM_SSL_VERIFY=false
```

或者直接在 CLI 上加：

```bash
python -m app.main run --config config.toml --insecure
```

不建议长期关闭 TLS 校验，最好还是配置自定义 CA 证书。
