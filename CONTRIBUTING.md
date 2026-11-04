# Contributing

Thanks for your interest! Bug reports, feature ideas and pull requests are welcome.

## Reporting bugs

Open an issue and include the `pptx-to-md --version`, your OS and Python version, the command you ran and the full
error. If a particular deck triggers it, a minimal `.pptx` that reproduces the problem helps a lot (please make sure
it contains nothing confidential). **Never paste API keys or AWS credentials.**

## Development setup

```bash
git clone https://github.com/kursluzz/pptx-to-md && cd pptx-to-md
uv sync --all-extras
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

Tests must not call real LLM APIs: use the fake backend in `tests/conftest.py`. Decks used in tests are generated with
python-pptx, so no binary fixtures are committed.

## Pull requests

- Keep them focused; one change per PR.
- Add or update tests, and update `README.md` and `CHANGELOG.md` (under "Unreleased") for user-visible changes.
- Make sure CI is green (tests on 3.11-3.13 and ruff).
- Adding an LLM provider: implement a backend with a `complete(prompt, image, max_tokens)` method in `llm.py`
  (raise `RetryableError` for throttling), register it in `make_backend` and `config.PROVIDERS`, and add the
  questions to `configure.py`.

By contributing you agree that your contribution is licensed under the MIT license.
