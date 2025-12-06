# OpenAI API Setup Guide

## Overview

This application uses OpenAI's GPT models for AI-powered social media copy generation. The integration favors secure defaults and keeps keys out of source control.

## Quick Start

### 1. Get Your OpenAI API Key
1. Visit [OpenAI Platform](https://platform.openai.com/)
2. Sign up or log in
3. Navigate to **API Keys** and click **Create new secret key**
4. Copy the key (starts with `sk-...`) and store it somewhere safe

### 2. Configure the API Key
Choose one of the two supported methods:

#### Option A: Environment Variable (recommended)
```bash
# macOS/Linux
export OPENAI_API_KEY='sk-your-api-key-here'

# Optional: persist in your shell profile
echo "export OPENAI_API_KEY='sk-your-api-key-here'" >> ~/.zshrc
source ~/.zshrc
```

```powershell
# Windows (PowerShell)
$env:OPENAI_API_KEY='sk-your-api-key-here'
```

#### Option B: Local secrets file
Create a TOML file to keep secrets out of your shell history:
```bash
mkdir -p config
cat <<'TOML' > config/secrets.toml
OPENAI_API_KEY = "sk-your-api-key-here"
TOML
```
Point the app at a custom path with `GSP_SECRETS_FILE=/path/to/secrets.toml`.
Add the file to `.gitignore` so it never lands in version control.

### 3. Verify setup
Run a quick LLM invocation via the CLI:
```bash
python -m greek_sub_publisher.cli tests/data/demo.mp4 --output /tmp/out.mp4 --llm-social-copy --artifacts /tmp/artifacts
```
If the key is missing, the CLI will raise a clear error describing how to supply it.

## Security Best Practices
- Store API keys in environment variables or `config/secrets.toml`
- Keep secret files out of git (`echo "config/secrets.toml" >> .gitignore`)
- Rotate API keys periodically and set OpenAI usage limits
- Use separate keys for dev/staging/production
- Never expose keys in client-side code

## Model Configuration
Default model: **gpt-4o-mini**

Why gpt-4o-mini?
- ⚡ Fast responses
- 💰 Low cost compared to GPT-4
- 🎯 Great for titles/descriptions
- 📊 High throughput

Alternative models can be set in `src/greek_sub_publisher/config.py`:
```python
SOCIAL_LLM_MODEL = "gpt-4o-mini"  # default
# SOCIAL_LLM_MODEL = "gpt-4o"      # higher quality, higher cost
# SOCIAL_LLM_MODEL = "gpt-3.5-turbo"  # legacy
```

## Error handling
Common issues are handled with actionable messages:
- **Missing API key**: instructs you to set `OPENAI_API_KEY` or populate `config/secrets.toml`
- **Invalid API key**: reports `AuthenticationError` from the OpenAI SDK
- **Rate limits or quota errors**: surfaced directly so you can pause or upgrade your plan

## API key priority
Keys are resolved in this order:
1. Explicit parameter (when passed to helper functions)
2. Environment variable (`OPENAI_API_KEY`)
3. Secrets file (`GSP_SECRETS_FILE` if set, otherwise `config/secrets.toml` if present)

UI defaults for the FastAPI/Next.js app (AI toggle, model, temperature, upload cap) live in `config/app_settings.toml`; copy `config/app_settings.example.toml` to get started.
