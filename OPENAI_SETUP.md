# OpenAI API Setup Guide

## Overview

This application uses OpenAI's GPT models for AI-powered social media copy generation. The implementation is secure, professional, and supports multiple configuration methods.

## Quick Start

### 1. Get Your OpenAI API Key

1. Visit [OpenAI Platform](https://platform.openai.com/)
2. Sign up or log in
3. Navigate to **API Keys** section
4. Click **"Create new secret key"**
5. Copy the key (starts with `sk-...`)
6. ⚠️ **Save it securely** - you won't be able to see it again

### 2. Configure API Key

Choose one of three methods:

#### **Option A: Environment Variable** (Recommended for local development)

```bash
# macOS/Linux
export OPENAI_API_KEY='sk-your-api-key-here'

# Add to ~/.zshrc or ~/.bashrc for persistence
echo "export OPENAI_API_KEY='sk-your-api-key-here'" >> ~/.zshrc
source ~/.zshrc
```

```bash
# Windows (PowerShell)
$env:OPENAI_API_KEY='sk-your-api-key-here'
```

#### **Option B: Streamlit Secrets** (Recommended for deployed apps)

1. Create `.streamlit/secrets.toml` in your project root:
   ```bash
   mkdir -p .streamlit
   touch .streamlit/secrets.toml
   ```

2. Add your key:
   ```toml
   OPENAI_API_KEY = "sk-your-api-key-here"
   ```

3. ⚠️ **Important**: Add to `.gitignore`:
   ```bash
   echo ".streamlit/secrets.toml" >> .gitignore
   ```

#### **Option C: Streamlit Cloud Secrets** (For cloud deployment)

1. Go to your Streamlit Cloud app dashboard
2. Click **Settings** → **Secrets**
3. Add:
   ```toml
   OPENAI_API_KEY = "sk-your-api-key-here"
   ```

### 3. Verify Setup

Run the Streamlit app:
```bash
streamlit run app.py
```

- If configured correctly: Toggle "Enable AI Enrichment" ✅
- If not configured: Toggle disabled with warning message ⚠️

---

## Security Best Practices

### ✅ DO:
- Store API keys in environment variables or Streamlit secrets
- Add `.streamlit/secrets.toml` to `.gitignore`
- Rotate API keys periodically
- Set usage limits in OpenAI dashboard
- Use separate keys for dev/staging/production

### ❌ DON'T:
- Hardcode API keys in source code
- Commit API keys to version control
- Share API keys in chat/email
- Use production keys in development
- Expose keys in client-side code

---

## Model Configuration

Default model: **gpt-4o-mini**

**Why gpt-4o-mini?**
- ⚡ **Fast**: 2-3 second response time
- 💰 **Affordable**: ~15x cheaper than GPT-4
- 🎯 **Excellent for social copy**: Perfect quality for titles/descriptions
- 📊 **High throughput**: Can handle many requests

### Cost Estimate

For social copy generation (typical usage):
- Input: ~200 tokens (transcript)
- Output: ~150 tokens (3 platform copies)
- Cost per video: **~$0.0001 USD** (less than a penny!)

### Alternative Models

Edit `src/greek_sub_publisher/config.py`:

```python
# Faster and cheaper (default)
SOCIAL_LLM_MODEL = "gpt-4o-mini"

# Higher quality (more expensive)
SOCIAL_LLM_MODEL = "gpt-4o"

# Legacy (not recommended)
SOCIAL_LLM_MODEL = "gpt-3.5-turbo"
```

### Streamlit AI defaults (UI)

For the Streamlit app you can control AI defaults in `.streamlit/config.toml` (non-secret):
```toml
[ai]
enable_by_default = false  # set true to pre-toggle AI when a key is present
model = "gpt-4o-mini"      # default model for UI
temperature = 0.6          # sampling temperature for generation
```
Keep your real API key in `.streamlit/secrets.toml` (see above) and leave `config.toml` committed.

---

## Error Handling

The implementation includes comprehensive error handling:

### Missing API Key
```
RuntimeError: OpenAI API key is required for AI enrichment. Please set it via:
  1. Environment variable: export OPENAI_API_KEY='your-key'
  2. Streamlit secrets: Add OPENAI_API_KEY to .streamlit/secrets.toml
  3. Pass explicitly via api_key parameter
```

### Invalid API Key
```
openai.AuthenticationError: Incorrect API key provided
```
→ Double-check your key in OpenAI dashboard

### Rate Limit Exceeded
```
openai.RateLimitError: Rate limit exceeded
```
→ Wait or upgrade your OpenAI plan

### Insufficient Quota
```
openai.RateLimitError: You exceeded your current quota
```
→ Add billing info in OpenAI account

---

## API Key Priority

The system checks for API keys in this order:

1. **Explicit parameter** (if passed to function)
2. **Environment variable** (`OPENAI_API_KEY`)
3. **Streamlit secrets** (`st.secrets.OPENAI_API_KEY`)

First found wins. This allows flexibility for different deployment scenarios.

---

## Usage Examples

### CLI with Environment Variable
```bash
export OPENAI_API_KEY='sk-...'
python -m greek_sub_publisher.cli process video.mp4 -o output.mp4 --llm-social-copy
```

### Streamlit with Secrets File
```bash
# .streamlit/secrets.toml contains OPENAI_API_KEY
streamlit run app.py
```

### Programmatic Usage
```python
from greek_sub_publisher.subtitles import build_social_copy_llm

# Option 1: Use environment variable
social = build_social_copy_llm(transcript)

# Option 2: Pass key explicitly
social = build_social_copy_llm(transcript, api_key="sk-...")
```

---

## Monitoring & Limits

### Check Usage
1. Visit [OpenAI Usage Dashboard](https://platform.openai.com/usage)
2. Monitor API calls and costs
3. Set up budget alerts

### Set Limits (Recommended)
1. Go to **Billing** → **Usage limits**
2. Set hard limit (e.g., $10/month)
3. Set soft limit email alerts (e.g., $5/month)

---

## Troubleshooting

### Toggle is disabled in Streamlit
**Cause**: No API key detected  
**Fix**: Set `OPENAI_API_KEY` in environment or secrets

### "API key is required" error
**Cause**: Key not found in any source  
**Fix**: Check environment variables and secrets files

### Slow response times
**Cause**: Network latency or OpenAI API load  
**Fix**: Normal for cloud APIs (2-5 seconds). If persistent, check OpenAI status page

### InvalidRequestError
**Cause**: Malformed request or unsupported model  
**Fix**: Verify model name in config.py

---

## Production Deployment Checklist

- [ ] API key added to Streamlit Cloud secrets
- [ ] `.streamlit/secrets.toml` in `.gitignore`
- [ ] Usage limits set in OpenAI dashboard
- [ ] Budget alerts configured
- [ ] Error handling tested
- [ ] Separate production API key (not dev key)

---

## Additional Resources

- [OpenAI API Documentation](https://platform.openai.com/docs)
- [OpenAI Pricing](https://openai.com/pricing)
- [Streamlit Secrets Management](https://docs.streamlit.io/streamlit-community-cloud/deploy-your-app/secrets-management)
- [API Best Practices](https://platform.openai.com/docs/guides/safety-best-practices)

---

## Support

For issues:
1. Check this guide
2. Verify API key is set correctly
3. Check OpenAI status page
4. Review error messages for specific guidance
