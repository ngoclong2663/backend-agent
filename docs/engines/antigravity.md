# Antigravity CLI (`agy`) — spike results and adapter notes

Spike for Story 3.3, run 2026-10-23 against **agy 1.4.6** (installed in a throwaway `python:3.12-slim` container).
Adapter: `agent-api/src/engines/antigravity/`.

**Verdict: go**, with API-key or ADC auth in Docker, or the `agy` account login on the host. A real generation
was run on 2026-10-26 with the account login (see *Real run* below).

## Findings

| Question | Finding | Source |
|---|---|---|
| Install | Go binary from `curl -fsSL https://antigravity.google/cli/install.sh \| bash` (→ `~/.local/bin/agy`). The script always installs *latest* from a manifest (`…/manifests/linux_amd64.json`: `version`, `url`, `sha512`), so the worker image pins the tarball URL + sha512 directly. The documented `--skip-aliases` flag is rejected by the current script. | verified |
| Headless mode | `agy -p "<prompt>"`, or **stream-json stdin mode**: `--input-format stream-json --output-format stream-json`, one `{"event":"user","message":{"content":"…"}}` line per turn; the process ends when stdin closes. The adapter uses stdin mode (no argv length limit; it is the documented subprocess integration). | docs + verified |
| Output events | NDJSON with `event`: `init` (`conversation_id`, `tools`, `permission_mode`), `step_update` (`step_index`, `state` ACTIVE/DONE, `step_type` `agent_response`/`tool`/…, `text_delta`, `tool_info{name, parameters, output, error}`), `result` (`status` SUCCESS/ERROR/CANCELED/…, `response`, `error`, `num_turns`, `usage{input_tokens, output_tokens, thinking_tokens, cache_read_tokens, total_tokens}`). **No cost field.** | docs; `result` verified |
| Exit codes | 0 success (also when a tool was soft-denied); 1 failed run (e.g. auth). Unauthenticated run printed `{"event":"result","result":{…"status":"ERROR","error":"authentication failed or timed out"…}}` and `Error: authentication required…` on stderr, exit 1. | verified |
| Approvals / tools | `--mode accept-edits`; headless soft-denies shell commands by default. Permission rules live in `~/.gemini/antigravity-cli/settings.json` → `permissions.allow/deny/ask` with `action(target)` (`read_file`, `write_file`, `command`, `read_url`, `execute_url`, `mcp`). The adapter writes a per-job settings file that denies `command(*)`, URL access and MCP. `--sandbox` / `enableTerminalSandbox` restricts the terminal. | docs |
| Auth | **Host:** the `agy` account login (`ANTIGRAVITY_AUTH=account`) keeps its token in the OS keyring over D-Bus, so it works headless from the host dev worker even with a per-job `HOME`; no `GEMINI_API_KEY` needed. **In a container** the keyring is missing → the adapter reports the engine unavailable. Supported for us: `GEMINI_API_KEY` **plus** `"modelProvider": "gemini"` in settings.json (the key alone is ignored), or ADC (`AGY_ADC_AUTH=true` + `GOOGLE_APPLICATION_CREDENTIALS`). | docs |
| Subprocess hang ([issue #318](https://github.com/google-antigravity/antigravity-cli/issues/318)) | Reported for `agy -p` with piped stdout. Stdin stream-json mode returned promptly over pipes in the probe (auth-error path). **PTY fallback not implemented**; revisit if an authenticated run hangs. | partially verified |
| Context files | `AGENTS.md`, `GEMINI.md`, `.agents/AGENTS.md`, `.agents/rules/*.md` (needs frontmatter). Max 24 KB per file. | docs |
| Skills | Workspace skills at `.agents/skills/<name>/SKILL.md`. | docs |
| Max turns | **No flag.** The adapter counts finished `agent_response` steps and stops the process past `max_turns` (`limit_exceeded`/`max_turns`). `--print-timeout` bounds wall-clock time. agy emits one `agent_response` per tool call, so its turns are far smaller than Claude's: it gets its own limits (`ANTIGRAVITY_MAX_TURNS=150`, `ANTIGRAVITY_TIMEOUT_SECONDS=2400`). | docs + real run |
| Self-update | The binary keeps updater state under `$HOME` (`updater/`, `last_check.timestamp`). Each job gets its own `HOME`; whether agy self-updates the pinned binary in place is unverified. | observed |

## Adapter decisions

- Per-job `HOME` (`<state>/engine-home/antigravity/`) holding the generated `settings.json`; nothing from the worker's own home is used.
- `prepare_workspace`: skills → `.agents/skills/`, conventions → managed section in `AGENTS.md` (points at the template's `CLAUDE.md` when present).
- Before every run `.agents/hooks.json` and `.agents/rules/` are removed from the workspace, so generated content cannot plant hooks or rules.
- Scoped read/write (Story 18.4): `permissions.allow` contains only `read_file(<workdir>)` and `write_file(<workdir>)` for the request's resolved workdir, preventing `agy` from reading files outside its working directory.
- Model per purpose (Story 18.5): `ANTIGRAVITY_PURPOSE_MODELS` overrides the model for specific calls (default: `generate_assets` runs on `gemini-3.8-flash-low`), while other purposes use `ANTIGRAVITY_MODEL`.
- Usage: `input_tokens + cache_read_tokens` → input, `output_tokens + thinking_tokens` → output, cost estimated against model pricing.

## Policy note

A forum reply (not confirmed as Google staff) says orchestrating `agy` headless via process pipes is supported and
consumes the same entitlements as interactive use, while extracting OAuth tokens is not. Related threads about
consumer plans were still open in October 2026. Our container setup uses API keys or ADC, not account logins.
[forum thread](https://discuss.ai.google.dev/t/is-external-orchestration-of-antigravity-cli-headless-mode-supported-with-account-based-usage/183051)

## Real run (2026-10-26, account login, host dev worker)

Spec: `examples/specs/two-entity.json` (2 models, 10 operations). Limits at the time: 40 turns, 900 s per call.

| Step | Result |
|---|---|
| `generate_database` | ok in 310 s (Claude Code: ~41 s); migration upgrade/check/downgrade passed; schema matches the plan |
| `generate_backend` | **failed** after 400 s: `limit_exceeded (max_turns)`; it had written one repository port + implementation. ~2.9 M input / 132 k output tokens |

Second run with the per-engine limits (150 turns, 2400 s):

| Step | Result |
|---|---|
| `generate_database` | ok in 314 s |
| `generate_backend` | **ok**: both modules, 47 files, 15.5 min |
| `generate_tests` | failed: `cli_error (rate_limit)`: "Individual quota reached … Resets in 167h" (account quota, after ~8.6 M input / 271 k output tokens for the run) |

Takeaways: auth, skills and the permission rules work headless; agy is slower and explores more than Claude Code,
and the shared 40-turn cap was too small for it, hence the per-engine limits above. Cost is not reported by agy.

## To do before relying on it

1. Finish a full generation (tests + validation) once the account quota resets, or with `GEMINI_API_KEY`. A full
   two-entity run costs roughly 9 M input tokens on agy, which a consumer account quota may not cover.
2. Confirm no self-update happens inside the worker image.
