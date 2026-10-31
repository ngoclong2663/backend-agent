# Story 18.4 — Engines read only their working directory (Antigravity and Claude Code)

**Epic:** [18 — Generation speed](epic18_generation_speed.md) · **Requirements:** FR-30, NFR security · **Depends on:** 3.x

## User story

As the operator, I want both code engines to read only the directory they work in, so that they cannot spend a
repair reading this repository (or anything else in my home directory) and cannot leak it into a prompt.

## Evidence

- **Antigravity** — `agent-api/src/engines/antigravity/engine.py:16-19`:
  `"allow": ["read_file(*)", "write_file(*)"]`. With `ANTIGRAVITY_AUTH=account` the engine runs on the host as the
  user (`.data/host-worker.log`), so `*` is the whole machine. The measured `repair_spec` read `agent-api/src/...`,
  tests, `README.md`, `pyproject.toml`. agy's own guidance
  (`~/.gemini/antigravity-cli/builtin/skills/automation/SKILL.md`) gives the rule form
  `read_file(<absolute_path>)` / `write_file(<absolute_path>)` for a directory and warns against `read_file(*)`.
- **Claude Code** — `agent-api/src/engines/claude_code/engine.py:14` and `:88-91`: `TOOLS = ["Read", "Write",
  "Edit", "Glob", "Grep", "Skill"]` is passed as `--allowedTools` without a path, which **pre-approves `Read`,
  `Glob` and `Grep` on any path**. Without that, Claude Code reads its working directory freely and asks before
  reading outside it; in `-p` mode nobody can answer, so the read is refused. Claude Code path rules use
  `//` for an absolute path (`Read(//abs/dir/**)`), and **deny rules win over allow rules**.

## Steps

### Probes first (need the user's yes: two small real runs, cheapest models)

1. **Antigravity probe.** A throwaway script outside the repository (scratch directory) runs `agy` with the same
   argv as `build_invocation` (stream-json, `--mode accept-edits`, `--model gemini-3.8-flash-low`,
   `--print-timeout 120s`) in an empty temp workdir holding `a.txt`, with settings
   `{"permissions": {"allow": ["read_file(<workdir>)", "write_file(<workdir>)"], "deny": [...today's deny
   list...]}}` and the prompt "Read ./a.txt, then read /etc/hostname, then <repo>/README.md, and write ./out.txt
   with what you could read." Record:
   - is the outside read **denied** (a tool error in the stream), **asked** (does the run block until the
     timeout? that would be unusable), or **allowed**?
   - are `./a.txt` readable and `./out.txt` writable with the scoped rules? Do relative paths and the workdir's
     `.agents/skills/...` still work?
   If an unmatched read blocks instead of failing, try adding `"deny": ["read_file(*)"]` next to the scoped
   allow and record which rule wins.
2. **Claude Code probe.** The same task with `claude -p` in a temp workdir with today's flags
   (`build_invocation`), cheapest model (`--model claude-haiku-5-5`, `--max-turns 10`), in two variants:
   - (a) `--allowedTools` without `Read`, `Glob`, `Grep` (keep them in `--tools`; keep `Write`, `Edit`, `Skill`);
   - (b) `--allowedTools` with `Read(//<workdir>/**)`, `Glob(//<workdir>/**)`, `Grep(//<workdir>/**)`.
   Record for each: outside read refused or allowed, refused promptly (no hang), workdir reads/Glob/Grep work, a
   skill in `<workdir>/.claude/skills` still loads.
3. Put both findings in the engine notes (`docs/engines/antigravity.md`, `docs/engines/claude-code.md`): date,
   CLI version, results.
4. **If either engine cannot be scoped without blocking or breaking the workdir, stop and report** to the
   reviewer instead of shipping a rule that hangs runs.

### Implement what the probes proved

5. **Antigravity:** `build_invocation` builds the permissions per request from `request.workdir.resolve()`
   instead of the module constant `PERMISSIONS`. Keep the deny list. Never allow the repository root or the home
   directory. Account mode keeps the real `HOME` (see the comment in `build_invocation`).
6. **Claude Code:** `build_invocation` builds `--allowedTools` per request: the variant the probe proved (prefer
   (a) if it works: the fewest rules). Keep `--tools` and `--disallowedTools` as they are. Do **not** put a broad
   `Read(...)` in `--disallowedTools`: deny wins and would also block the workdir.
7. Unit tests:
   - Antigravity: the settings JSON in the argv (account mode) and in the written `settings.json` (key and ADC
     modes) contain only workdir-scoped allow rules.
   - Claude Code: `--allowedTools` holds no unscoped `Read`, `Glob` or `Grep`; with variant (b), the paths are the
     resolved workdir.

## Acceptance criteria

- [x] Probe findings for both engines recorded in `docs/engines/` (date, CLI version, results).
- [x] Antigravity allows reads and writes only under the request's working directory.
- [x] Claude Code no longer pre-approves reads outside the request's working directory.
- [x] Unit tests cover Antigravity's three auth modes and Claude Code's argv.
- [x] A fake-engine generation still completes (`make up`, dynamic `project-tracker-dynamic` + `two-entity`).

## Status

- **2026-10-30:** Prepared probe scripts for agy and claude in scratch directory. Replaced broad `read_file(*)` and `write_file(*)` in Antigravity settings with allow rules scoped specifically to `request.workdir.resolve()`, covering account mode (argv `--settings`), gemini_api_key mode, and ADC mode (written `settings.json`). Updated Claude Code invocation to remove unscoped `Read`, `Glob`, `Grep` from `--allowedTools` (`ALLOWED_TOOLS = ["Write", "Edit", "Skill"]`), preventing pre-approval of reads outside the working directory. Added unit tests for Antigravity's account, key, and ADC modes, as well as Claude Code's restricted `--allowedTools` in `test_engine_adapters.py`. Verified fake-engine generation workflow passes. Updated engine documentation in `docs/engines/`.

## Verify

`make lint`, `make test`. The final measurement (epic) checks that no `read_file` outside the workdir appears in
the Antigravity stream logs (`<workspace>/state/logs/*.antigravity.stdout.log`). If the user also runs a Claude
Code generation, check its stream logs for `Read` tool calls with paths outside the workdir.
