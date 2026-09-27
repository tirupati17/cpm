---
name: service-task
description: One sentence an agent can match against a request. Say WHEN to use it ("Use when publishing ...", "Use when a push never arrives ..."), not what the service is.
---

# <Service>: <task>

## Credentials

`cpm creds setup <service>` asks for each one and says where it lives:

| Name | Where to get it |
|---|---|
| `SERVICE_API_KEY` | Dashboard > Settings > API keys. Least privilege. |

## Commands

```bash
cpm <service> <command>            # dry run: shows what would change
cpm <service> <command> --commit   # does it
```

## Order

1. ...

## Traps

- **<Symptom as the user sees it>.** Cause. How to tell. What to do instead.
