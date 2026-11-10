# Security

- Never put a Tripo API key in this repository. Keys are read from the `TRIPO_API_KEY` environment variable or
  from a local config file outside the project (see the README).
- `python3 -m helpers3d scan` finds keys and private paths before you commit. The pre-commit hook in `.githooks/`
  runs it for you: `git config core.hooksPath .githooks`.
- If you find a security problem, open a private security advisory on GitHub instead of a public issue.
