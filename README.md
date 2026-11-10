# france-grid-analytics

Analytics on the French power system built on the
[ENTSO-E Transparency Platform](https://transparency.entsoe.eu) API.

Work in progress.

## Setup

```bash
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env            # then put your own ENTSO-E token in .env
git config core.hooksPath .githooks
```

The token is read from the `ENTSOE_API_TOKEN` environment variable or from the git-ignored `.env`
file. It is only ever sent directly to `https://web-api.tp.entsoe.eu` over HTTPS. System proxy
settings are ignored on purpose.

## Checks

```bash
python scripts/check_secrets.py --all   # blocks token-like strings in tracked files
ruff check . && ruff format --check .
mypy
pytest
```
