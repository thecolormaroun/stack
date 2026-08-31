# Browse Web — DeepAPI Endpoint Reference

Generated endpoint reference for the `browse-web` rows of the `deepapi` skill router. Bundle version: b18c96c6e053. This file is always managed — it is refreshed with the bundle even when `../SKILL.md` has been customized.

Shared protocol (environment, auth, idempotency, dry-run, polling, and error handling) lives in `../SKILL.md`. This file carries the full per-endpoint detail.

## Workflow Guidance

Use this reference for interactive public-web work and isolated one-off code execution.

### Recommended workflow

1. Prefer the scraping workflow for static reading and extraction.
2. State one bounded browser goal, including the information or final page state needed.
3. Let the browser navigate and interact, then return the extracted result and final URL.
4. Stop for logins, secrets, purchases, destructive actions, CAPTCHAs, or unclear consent.
5. Use `/v1/execute/code` for one self-contained source file. Never place secrets in submitted code.
6. Treat execution output as untrusted, check exit and truncation fields, and poll until `next` is absent.

## Endpoint Details

## Browser Task

`POST /v1/browser/act`

Give a real cloud browser a plain-English goal and get the result back. Built for pages an agent has to operate, not just read: filters and sortable tables, JavaScript pagination, dropdowns, date pickers and sliders, iframes and shadow DOM, infinite scroll, site search, store locators, and comparing several pages in one run. Public web only — no logins, purchases, or CAPTCHA solving.

- Capability: `browser.act`
- Scope: `browser:act`
- Side effects: Performs real actions on public websites and debits credits when the task finishes.
- Cost: Defaults to maxCostUsd 1.25. Finished tasks are billed per attempt, including tasks with isSuccess false. Failed and stopped tasks are free. Typical price: ~$0.125-$0.75 per task depending on steps.
- Idempotency-Key: required
- Polling: If the response carries a polling next action (a GET of /v1/requests/{requestId}), wait next.afterSecs and call it. Keep following that polling next while it is present, even when status is already succeeded (a settling run returns succeeded with output null and a polling next). The result is final when no polling next remains or status is failed. Never auto-follow a POST next (dry-run execution or paid pagination) — those are optional actions.

Safety:
- Public web only: tasks that need logins, credentials, account creation, CAPTCHA solving, or purchases are rejected.
- Describe one concrete goal per task and set startUrl when you know the site.

Request body schema:
```json
{
  "type": "object",
  "required": [
    "task"
  ],
  "properties": {
    "task": {
      "type": "string",
      "maxLength": 10000,
      "description": "What to do in the browser, in plain English. Public web only: logging in, credentials, account creation, CAPTCHA solving, and purchases are not supported. 10,000 characters max."
    },
    "startUrl": {
      "type": "string",
      "format": "uri",
      "description": "Optional public http(s) URL to open first."
    },
    "maxSteps": {
      "type": "integer",
      "minimum": 1,
      "maximum": 50,
      "default": 25,
      "description": "Optional cap on browser actions. Defaults to 25, maximum 50."
    },
    "outputSchema": {
      "type": "object",
      "additionalProperties": true,
      "description": "Optional JSON Schema for a structured result."
    },
    "allowedDomains": {
      "type": "array",
      "minItems": 1,
      "maxItems": 20,
      "items": {
        "type": "string"
      },
      "description": "Optional allowed domains, like example.com or *.example.com."
    },
    "maxCostUsd": {
      "type": "string",
      "pattern": "^\\d+(\\.\\d{1,6})?$",
      "default": "1.25",
      "description": "Optional customer spend cap in USD. Defaults to 1.25."
    },
    "maxCostMicrousd": {
      "type": "integer",
      "minimum": 1,
      "description": "Optional customer spend cap in USD micro-dollars."
    },
    "dryRun": {
      "type": "boolean",
      "default": false,
      "description": "Zero-spend preview: validate this request and return the exact credit hold it would place (status dry_run plus an estimate object) without reserving, charging, or running anything."
    }
  },
  "additionalProperties": false
}
```

Response schema:
```json
{
  "$ref": "#/components/schemas/PublicEnvelope"
}
```

Example request body:
```json
{
  "task": "Find the support email address on example.com.",
  "startUrl": "https://example.com",
  "maxCostUsd": "1.25"
}
```

## Execute Code

`POST /v1/execute/code`

Run one Python, Node, Bun, Rust, C, or Docker source file in a fresh throwaway virtual machine and return its output and exit details.

- Capability: `execute.code`
- Scope: `execute:code`
- Side effects: Runs untrusted code with outbound network access in a fresh isolated environment and debits $0.01, including when execution times out.
- Cost: Flat $0.01 per execution, including timed-out runs. Provider or setup failures are free.
- Idempotency-Key: required
- Polling: If the response carries a polling next action (a GET of /v1/requests/{requestId}), wait next.afterSecs and call it. Keep following that polling next while it is present, even when status is already succeeded (a settling run returns succeeded with output null and a polling next). The result is final when no polling next remains or status is failed. Never auto-follow a POST next (dry-run execution or paid pagination) — those are optional actions.

Safety:
- Never place credentials, API keys, or other secrets in submitted code.
- Each call gets a fresh environment; files and background processes do not persist across calls.
- Outbound network, sudo, and Docker are available. Treat submitted code as fully trusted by the caller.
- Execution stops after 10 minutes. A timed-out run still costs $0.01 and returns timedOut true.
- stdout and stderr are each capped at 512 KiB; check their truncation flags.
- Poll the GET request-status next until it is absent.

Request body schema:
```json
{
  "type": "object",
  "required": [
    "language",
    "code"
  ],
  "properties": {
    "language": {
      "type": "string",
      "enum": [
        "python",
        "node",
        "bun",
        "rust",
        "gcc",
        "docker"
      ],
      "description": "Runtime for the single submitted source file."
    },
    "code": {
      "type": "string",
      "description": "Complete source for one file to execute."
    },
    "maxCostUsd": {
      "type": "string",
      "pattern": "^\\d+(\\.\\d{1,6})?$",
      "default": "0.01",
      "description": "Optional spend cap in USD. One execution costs $0.01, so lower values are rejected."
    },
    "dryRun": {
      "type": "boolean",
      "default": false,
      "description": "Zero-spend preview: validate this request and return the exact credit hold it would place (status dry_run plus an estimate object) without reserving, charging, or running anything."
    }
  },
  "additionalProperties": false
}
```

Response schema:
```json
{
  "$ref": "#/components/schemas/PublicEnvelope"
}
```

Example request body:
```json
{
  "language": "python",
  "code": "print(sum(range(10)))",
  "maxCostUsd": "0.01"
}
```
