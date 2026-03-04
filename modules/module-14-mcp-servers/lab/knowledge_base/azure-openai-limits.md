# Azure OpenAI Rate Limits and Quotas

## Default TPM Limits (tokens per minute)

| Model | GlobalStandard default |
|---|---|
| gpt-4o | 30,000 TPM |
| gpt-4o-mini | 200,000 TPM |
| text-embedding-3-small | 350,000 TPM |

## Retry Strategy

Azure OpenAI returns HTTP 429 when rate limits are hit. Recommended approach:
- Implement exponential backoff starting at 1 second
- Cap retries at 5 attempts
- Respect the `Retry-After` header if present

## Context Window Limits

| Model | Max context (tokens) |
|---|---|
| gpt-4o | 128,000 |
| gpt-4o-mini | 128,000 |

## Cost Notes (approximate, check Azure pricing for current rates)

- Input tokens cost less than output tokens
- Cached prompt tokens (Azure prompt caching) can reduce costs by 50%
- Embeddings are significantly cheaper than chat completions
