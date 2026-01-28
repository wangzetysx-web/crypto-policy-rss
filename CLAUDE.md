# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RSS aggregator that fetches crypto/finance news from multiple sources, translates to Chinese, and pushes to WeChat Work (企业微信) groups.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Dry-run mode (print only, no sending)
DRY_RUN=1 python main.py

# Actual run with webhook
WECOM_WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx" python main.py

# Debug mode
LOG_LEVEL=DEBUG DRY_RUN=1 python main.py
```

## Architecture

Single-file application (`main.py`) with this flow:

1. **Load configs** → `feeds.json` (RSS sources), `config.json` (keywords/settings)
2. **Load state** → `state.json` (tracks sent entries to prevent duplicates)
3. **For each feed**: Fetch RSS → Filter by keywords → Translate titles/summaries
4. **Send** → Batch messages to WeChat Work webhook (5 entries per message)
5. **Save state** → Update sent_ids with timestamps

Key components in `main.py`:
- `FeedSource`, `FeedEntry`, `AppConfig` - dataclasses for configuration
- `translate_to_chinese()` - uses `translators` lib with fallback engines (bing → google → alibaba → baidu → dictionary)
- `filter_entry()` - allow/deny keyword matching
- `send_wecom_message()` - WeChat Work API with retry/backoff
- `state.json` - deduplication via `{entry_id: timestamp}` map, auto-cleaned after retention period

## Configuration Files

- `feeds.json` - RSS source definitions (name, url, tags, enabled)
- `config.json` - keywords.allow/deny lists, settings (timeouts, batch sizes, retention)
- `state.json` - auto-generated, tracks sent entry IDs with timestamps

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `WECOM_WEBHOOK_URL` | Yes (unless DRY_RUN) | WeChat Work robot webhook |
| `DRY_RUN` | No | Set to `1` to print without sending |
| `LOG_LEVEL` | No | DEBUG/INFO/WARNING |

## GitHub Actions

Workflow in `.github/workflows/daily.yml` runs at **08:00 Beijing time** (UTC 00:00).
Manual triggers support dry_run, log_level, and force_run options.
State is persisted via git commits after each run.

## Constraints

- WeChat Work: max 4096 bytes per message, 20 messages/minute
- Translation: 1s delay between API calls to avoid rate limits
- Single source failure doesn't affect others (continues processing)
