# Security policy

Please report vulnerabilities privately using GitHub's
[private vulnerability reporting](https://github.com/kursluzz/pptx-to-md/security/advisories/new)
rather than a public issue. Expect an answer within a few days.

Things worth knowing:

- API keys and AWS keys entered in `pptx-to-md configure` are stored in plain text in the config file
  (permissions `0600` on Linux/macOS). Prefer environment variables, an AWS profile or SSO if that is a concern.
- With `--llm`, slide text and pictures are sent to the configured provider.
- Decks are parsed with [python-pptx](https://github.com/scanny/python-pptx); only convert files you trust.
