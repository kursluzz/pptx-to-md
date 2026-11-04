# Changelog

All notable changes are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/),
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0]

First public release.

- Convert `.pptx` files (or folders of them) to Markdown: titles, text, nested bullet lists, tables, chart labels,
  speaker notes and pictures (stored next to the Markdown file).
- No LLM by default. `--llm` adds picture text transcription and picture/slide descriptions.
- Providers: Amazon Bedrock (Amazon Nova by default) and OpenAI-compatible APIs.
- `pptx-to-md configure` stores provider settings in a per-user config file; environment variables override it.
- Token usage report and optional cost estimate.
