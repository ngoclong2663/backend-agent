# Claude Code CLI adapter

Adapter: `agent-api/src/engines/claude_code/`. Verified 2026-10-23 with Claude Code **2.1.245** (host) using a real
`claude -p` run; the worker image pins **2.1.309**.

## Invocation

```
claude -p --output-format stream-json --verbose --max-turns <n> --permission-mode acceptEdits
       --tools Read,Write,Edit,Glob,Grep,Skill --allowedTools Write,Edit,Skill
       --disallowedTools Bash,WebFetch,WebSearch,Write(.claude/**),Edit(.claude/**)
       --strict-mcp-config --append-system-prompt <guardrails> [--model <m>]
```

- The prompt goes over **stdin**. `cwd` is the job's project directory (checked to be under `WORKSPACE_ROOT`).
- `--tools` is what actually limits the tool set (`--allowedTools` only pre-approves). `--allowedTools` omits `Read`, `Glob`, and `Grep` (Story 18.4) so reads outside the workdir are not pre-approved; workdir reads/edits are permitted by `acceptEdits`. The real run reported exactly
  `["Edit","Glob","Grep","Read","Skill","Write"]`.
- **No shell**: generated code only ever runs in the sandbox (Epic 6).
- Writes under `.claude/` are denied, and `.claude/settings*.json`, `.claude/hooks`, `.mcp.json` are deleted before each
  run: project settings can define hooks, which run shell commands, so generated content must not be able to plant them.
  Verified: a prompt asking to create `.claude/settings.json` got "denied by your permission settings".

## Isolation and auth

- Per-job `HOME` and `CLAUDE_CONFIG_DIR` (`<state>/engine-home/claude_code/`) with onboarding pre-accepted; the worker's
  environment is not inherited (only `PATH`, `LANG`, `LC_ALL`, `TZ` + engine variables).
- Auth: `ANTHROPIC_API_KEY`, or a subscription login file (`CLAUDE_CREDENTIALS_HOST_FILE` → mounted read-only →
  copied per job with mode 0600). `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, `DISABLE_AUTOUPDATER=1`.

## Stream → normalized result

| stream-json | becomes |
|---|---|
| `system/init` | `system` event, `session_id` |
| `assistant` text / `tool_use` | `message` / `tool_use` events (paths made workspace-relative) |
| `user` `tool_result` | `tool_result` event (`ok:` / `error:`) |
| `result` | `turns`, usage (input = input + cache creation + cache read), `cost_usd = total_cost_usd`, final message; `error_max_turns` → `limit_exceeded/max_turns`; `is_error` → `cli_error` + reason (`auth`, `rate_limit`, `crash`) |

A sanitized recording of the real run is the parser fixture: `agent-api/tests/fixtures/engines/claude_stream_ok.jsonl`.
