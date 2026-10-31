"""Custom components (Story 17.3): the components of a rendered site that the section library does not have.

The scaffold registers each one's library fallback, so the site always builds. `generate_frontend` then resolves
every custom component, in parallel (at most `ENGINE_CONCURRENCY` engine calls at a time):

    cache hit   copy `ARTIFACT_ROOT/cache/components/<key>/<key>.tsx` into the site; no engine call, no checks
    miss        one engine call in a scratch copy of the frontend, then the isolated checks (conventions, tsc,
                ESLint, a render test with sample props on the mock API) in the component's own sandbox, repaired
                up to the repair limit; only the component's file is taken back, and cached when it passed
    failure     the engine fails or the checks still fail: the library fallback stays, with a warning

and points the registry at the result. The site-level checks (build, routes, smoke) run as for any rendered site.
"""

import asyncio
import contextlib
import hashlib
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.configs import config, get_logger
from src.modules.shared.domain.entities import ComponentCacheEntity
from src.modules.shared.domain.frontend_spec import iter_sections
from src.sandbox import ISandbox

from .checks.frontend_conventions import file_violations
from .component_cache import (
    PROMPT_VERSION,
    cached_file,
    component_file,
    component_key,
    overlay_metadata,
    sample_props,
    store_file,
)
from .context import EngineFailure, JobContext, RecordingSandbox
from .context_pack import component_context
from .contract import contract_operations
from .frontend_renderer import REGISTRY_FILE, custom_declarations, registry_ts, section_props
from .frontend_scaffold import update_owned

logger = get_logger(__name__)

SPEC_FILE = ".bga/component.json"
CONTEXT_PACK_FILE = ".bga/context.md"
RENDER_TEST = "tests/unit/custom-component.test.tsx"
TSCONFIG = "tsconfig.component.json"
DEFAULT_EXPORT = re.compile(r"^export default function [A-Z]", re.MULTILINE)
SCRATCH_IGNORE = shutil.ignore_patterns(
    ".git", "node_modules", ".next", "out", "test-results", "playwright-report", ".claude", ".agents", "*.tsbuildinfo"
)


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class Resolved:
    """How one custom component (one cache key; specs may give it several names) was resolved."""

    names: list[str]
    key: str
    status: str  # hit | generated | fallback
    engine_calls: int = 0
    engine_ms: int = 0
    saved_ms: int = 0  # a hit: the engine time it took to generate
    model: str | None = None
    reason: str | None = None
    failures: list[str] = field(default_factory=list)


class CustomComponents:
    def __init__(self, ctx: JobContext, plan: dict[str, Any], spec: dict[str, Any], contract: dict[str, Any] | None):
        self.ctx = ctx
        self.plan = plan
        self.spec = spec
        self.contract = contract
        self.declared = custom_declarations(spec)
        self.lock_sha256, self.overlay_version = overlay_metadata()
        self.slots = ctx.engine_slots if ctx is not None else asyncio.Semaphore(max(1, config.engine_concurrency))

    async def resolve(self, names: list[str] | None = None, max_repairs: int = 2) -> list[Resolved]:
        """Resolves the plan's custom components (or only `names`), records the result in the plan and the registry
        and returns one entry per cache key."""
        custom = self.plan["customComponents"]
        by_key: dict[str, list[str]] = {}
        for name in sorted(custom if names is None else names):
            by_key.setdefault(component_key(self.declared[name], self.lock_sha256, self.overlay_version), []).append(
                name
            )
        tasks = [asyncio.create_task(self._one(key, names, max_repairs)) for key, names in by_key.items()]
        try:
            results = await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        for result in results:
            for name in result.names:
                entry = custom[name]
                entry |= {"key": result.key, "status": result.status}
                if result.status == "fallback":
                    entry.pop("file", None)
                else:
                    entry["file"] = component_file(result.key)
        project = self.ctx.workspace.frontend
        (project / REGISTRY_FILE).write_text(registry_ts(self.plan))
        update_owned(project, [REGISTRY_FILE])  # generator-owned: auto-fix must not restore the scaffold's version
        return results

    def _section(self, name: str) -> dict[str, Any]:
        return next(
            section
            for route in self.plan["routes"]
            for section in iter_sections(route["sections"])
            if section["component"] == name
        )

    async def _one(self, key: str, names: list[str], max_repairs: int) -> Resolved:
        entry = self.ctx.store.component_cache(key)
        source = cached_file(key)
        if entry is not None and source.is_file():
            target = self.ctx.workspace.frontend / component_file(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            self.ctx.store.record_component_cache_hit(key)
            saved_ms = int(entry.saved_seconds * 1000)
            await self.ctx.emit(
                "component.cache_hit", step="generate_frontend", components=names, key=key, savedMs=saved_ms
            )
            return Resolved(names, key, "hit", saved_ms=saved_ms)
        async with self.slots:
            return await self._generate(key, names, max_repairs)

    async def _generate(self, key: str, names: list[str], max_repairs: int) -> Resolved:
        name = names[0]
        component = self.declared[name]
        relative = component_file(key)
        scratch = self.ctx.workspace.root / "scratch" / f"component-{key[:12]}"
        shutil.rmtree(scratch, ignore_errors=True)
        shutil.copytree(self.ctx.workspace.frontend, scratch, ignore=SCRATCH_IGNORE)
        self._write_check_files(scratch, name, component, relative)
        sandbox: ISandbox | None = None
        fill_task: asyncio.Task | None = None
        if self.ctx.sandboxes is not None:
            inner = self.ctx.sandboxes.for_job(self.ctx.generation_id, scratch, kind="frontend", part=f"c-{key[:10]}")
            sandbox = RecordingSandbox(inner, self.ctx)
            fill_task = asyncio.create_task(sandbox.shared_dependencies())
        result = Resolved(names, key, "generated")
        component_path = scratch / relative
        engine_error: str | None = None
        installed = False
        try:
            prompt = self.ctx.prompts.render(
                "generate_custom_component",
                PROMPT_VERSION,
                name=name,
                file=relative,
                description=component.get("description") or name,
                uses=component.get("uses") or [],
                props_schema_json=json.dumps(component.get("propsSchema") or {}, indent=2, sort_keys=True),
                spec_path=SPEC_FILE,
                test_path=RENDER_TEST,
            )
            sha_before = _file_sha256(component_path)
            try:
                await self._engine("generate_custom_component", prompt, scratch, result)
            except EngineFailure as exc:
                sha_after = _file_sha256(component_path)
                if sha_after is None or sha_after == sha_before:
                    return await self._fall_back(result, f"engine failed: {exc}")
                engine_error = str(exc)

            for attempt in range(1, max_repairs + 2):
                failures, installed = await self._checks(scratch, relative, sandbox, installed, fill_task=fill_task)
                if not failures:
                    break
                result.failures = failures
                if attempt > max_repairs:
                    reason = f"isolated checks still failing after {max_repairs} repairs"
                    if engine_error:
                        reason += f" (engine failed: {engine_error})"
                    return await self._fall_back(result, reason)
                prompt = self.ctx.prompts.render(
                    "repair_custom_component",
                    PROMPT_VERSION,
                    name=name,
                    file=relative,
                    attempt=attempt,
                    max_attempts=max_repairs,
                    failures="\n\n".join(failures)[:20_000],
                    test_path=RENDER_TEST,
                )
                sha_before = _file_sha256(component_path)
                try:
                    await self._engine("repair_custom_component", prompt, scratch, result)
                except EngineFailure as exc:
                    sha_after = _file_sha256(component_path)
                    if sha_after is None or sha_after == sha_before:
                        return await self._fall_back(result, f"engine failed: {exc}")
                    engine_error = str(exc)
            target = self.ctx.workspace.frontend / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(scratch / relative, target)
            cached = sandbox is not None  # only components that passed every isolated check are shared
            if cached:
                store_file(key, scratch / relative)
                self.ctx.store.save_component_cache(
                    ComponentCacheEntity(
                        key=key,
                        name=name,
                        source_generation_id=self.ctx.generation_id,
                        engine=self.ctx.engine.name,
                        model=result.model,
                        saved_seconds=result.engine_ms / 1000,
                    )
                )
            event_kwargs = {
                "step": "generate_frontend",
                "components": names,
                "key": key,
                "engineCalls": result.engine_calls,
                "cached": cached,
            }
            if engine_error is not None:
                event_kwargs["engineError"] = engine_error
            await self.ctx.emit("component.generated", **event_kwargs)
            return result
        except EngineFailure as exc:
            return await self._fall_back(result, f"engine failed: {exc}")
        finally:
            if fill_task is not None and not fill_task.done():
                fill_task.cancel()
            if sandbox is not None:
                await sandbox.stop()
            shutil.rmtree(scratch, ignore_errors=True)
            with contextlib.suppress(OSError):
                scratch.parent.rmdir()  # once the last component is done

    async def _engine(self, purpose: str, prompt, scratch: Path, result: Resolved) -> None:
        run = await self.ctx.run_engine("generate_frontend", purpose, prompt, repo="frontend", workdir_override=scratch)
        result.engine_calls += 1
        result.engine_ms += run.duration_ms
        if result.model is None:
            result.model = (run.usage.model if run.usage else None) or next(
                (call.model for call in run.model_calls if call.model), None
            )

    async def _fall_back(self, result: Resolved, reason: str) -> Resolved:
        result.status, result.reason = "fallback", reason
        fallbacks = {self.plan["customComponents"][name]["fallback"] for name in result.names}
        logger.warning(
            "custom component falls back to the library",
            extra={"generation_id": self.ctx.generation_id, "components": result.names, "reason": reason},
        )
        await self.ctx.emit(
            "component.fallback",
            step="generate_frontend",
            components=result.names,
            key=result.key,
            fallback=sorted(fallbacks),
            reason=reason,
            failures=[failure[:2000] for failure in result.failures[:5]],
        )
        return result

    # -- isolated checks -------------------------------------------------------------------------------------------

    def _write_check_files(self, scratch: Path, name: str, component: dict[str, Any], relative: str) -> None:
        section = self._section(name)
        props = sample_props(component.get("propsSchema")) | section_props(self.plan, self.spec, self.contract, section)
        spec = scratch / SPEC_FILE
        spec.parent.mkdir(parents=True, exist_ok=True)
        spec.write_text(
            json.dumps(
                {
                    "name": name,
                    "file": relative,
                    "description": component.get("description"),
                    "uses": component.get("uses") or [],
                    "propsSchema": component.get("propsSchema") or {},
                    "sampleProps": props,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        test = scratch / RENDER_TEST
        test.parent.mkdir(parents=True, exist_ok=True)
        test.write_text(render_test(relative, props, self._route_params(props.get("binding")), self._dynamic))
        context_doc = scratch / CONTEXT_PACK_FILE
        context_doc.parent.mkdir(parents=True, exist_ok=True)
        context_doc.write_text(component_context(scratch, component, props))
        tsconfig = {
            "extends": "./tsconfig.json",
            "compilerOptions": {"incremental": False},
            "include": ["next-env.d.ts", "src/**/*.d.ts", relative, RENDER_TEST],
        }
        (scratch / TSCONFIG).write_text(json.dumps(tsconfig, indent=2) + "\n")

    @property
    def _dynamic(self) -> bool:
        return self.plan["project"]["mode"] == "dynamic"

    def _route_params(self, binding: dict[str, Any] | None) -> dict[str, str]:
        """`$route.<name>` → the id of the operation's first fixture record, so a get finds its record."""
        params = {}
        for value in ((binding or {}).get("params") or {}).values():
            if isinstance(value, str) and value.startswith("$route."):
                params[value.removeprefix("$route.")] = self._fixture_id(binding["operationId"])
        return params

    def _fixture_id(self, operation_id: str) -> str:
        if not self.contract:
            return "1"
        operation = contract_operations(self.contract).get(operation_id) or {}
        entity = (operation.get("operation", {}).get("x-bga") or {}).get("entity")
        records = ((self.contract.get("x-bga") or {}).get("fixtures") or {}).get(entity) or [{}]
        return str(records[0].get("id", "1"))

    async def _checks(
        self,
        scratch: Path,
        relative: str,
        sandbox: ISandbox | None,
        installed: bool,
        fill_task: asyncio.Task | None = None,
    ) -> tuple[list[str], bool]:
        """Failures of the component's isolated checks (empty: it passed). Without a sandbox only the static ones
        run (tests with the fake validator), and the component is not cached."""
        path = scratch / relative
        if not path.is_file():
            return [f"{relative} was not written"], installed
        text = path.read_text(errors="replace")
        failures = [] if DEFAULT_EXPORT.search(text) else [f"{relative}: no `export default function`"]
        failures += [
            f"{item['file']}:{item['line'] or 1} {item['rule']}: {item['message']}"
            + (f" ({item['hint']})" if item.get("hint") else "")
            for item in file_violations(relative, text)
        ]
        if failures or sandbox is None:
            return failures, installed
        if not installed:
            shared = None
            if fill_task is not None:
                try:
                    shared = await fill_task
                except Exception as exc:
                    logger.warning(
                        "shared dependencies prewarm failed: %s",
                        exc,
                        extra={"generation_id": self.ctx.generation_id},
                    )
            else:
                shared = await sandbox.shared_dependencies()
            if shared is None:
                run = await sandbox.exec("pnpm install --frozen-lockfile --offline", timeout_s=600)
                if not run.ok:
                    return [f"pnpm install failed:\n{run.output[-3000:]}"], installed
        typecheck = await sandbox.exec(f"pnpm exec tsc -p {TSCONFIG} --pretty false", timeout_s=300)
        if not typecheck.ok:
            failures.append(f"typecheck (tsc) failed:\n{typecheck.output[-4000:]}")
        lint = await sandbox.exec(f"pnpm exec eslint {relative} {RENDER_TEST}", timeout_s=300)
        if not lint.ok:
            failures.append(f"lint (ESLint) failed:\n{lint.output[-4000:]}")
        if typecheck.ok and lint.ok:
            render = await sandbox.exec(
                f"pnpm exec vitest run {RENDER_TEST} --testTimeout=20000",
                timeout_s=config.frontend_component_test_timeout_seconds,
            )
            if not render.ok:
                output = render.output
                if render.timed_out:
                    hint = (
                        "render test timed out: most likely an endless render loop "
                        "(state set in an effect on every render)"
                    )
                    output = f"{output}\n{hint}" if output else hint
                failures.append(f"render test failed:\n{output[-4000:]}")
        return failures, True


def render_test(relative: str, props: dict[str, Any], route_params: dict[str, str], dynamic: bool) -> str:
    """Renders the component with sample props (dynamic: on the mock API) and fails on any React error."""
    module = relative.removeprefix("src/").removesuffix(".tsx")
    mocks = (
        'import { setApiBase } from "@/lib/api/client";\nimport { server } from "@/mocks/server";\n' if dynamic else ""
    )
    server = (
        'beforeAll(() => {\n  setApiBase("http://localhost/mock-api");\n'
        '  server.listen({ onUnhandledRequest: "warn" });\n});\nafterAll(() => server.close());\n\n'
        if dynamic
        else ""
    )
    hooks = "afterAll, beforeAll, " if dynamic else ""
    return (
        "// Generated by the Fullstack Generation Agent: the isolated render test of one custom component.\n"
        'import { act, render } from "@testing-library/react";\n'
        'import { QueryClient, QueryClientProvider } from "@tanstack/react-query";\n'
        'import { Profiler, type ComponentType } from "react";\n'
        f'import {{ {hooks}expect, it, vi }} from "vitest";\n'
        + mocks
        + f'import Component from "@/{module}";\n\n'
        + 'vi.mock("next/navigation", () => ({\n'
        + f"  useParams: () => ({json.dumps(route_params)}),\n"
        + '  usePathname: () => "/",\n'
        + "  useSearchParams: () => new URLSearchParams(),\n"
        + "  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), refresh: vi.fn() }),\n"
        + "}));\n\n"
        + f"const props: Record<string, unknown> = {json.dumps(props, indent=2, ensure_ascii=False)};\n"
        + "const Rendered = Component as unknown as ComponentType<Record<string, unknown>>;\n\n"
        + server
        + 'it("renders with sample props", async () => {\n'
        + "  let commits = 0;\n"
        + '  const errors = vi.spyOn(console, "error").mockImplementation((...args) => {\n'
        + '    const text = args.map(String).join(" ");\n'
        + '    if (text.includes("Maximum update depth exceeded")) {\n'
        + "      throw new Error(\n"
        + '        "render loop: the component re-rendered more than 50 times; " +\n'
        + '        "do not set state from an effect on every render",\n'
        + "      );\n"
        + "    }\n"
        + "  });\n"
        + "  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });\n"
        + "  render(\n"
        + "    <Profiler\n"
        + '      id="loop-guard"\n'
        + "      onRender={() => {\n"
        + "        if (++commits > 50) {\n"
        + "          throw new Error(\n"
        + '            "render loop: the component re-rendered more than 50 times; " +\n'
        + '            "do not set state from an effect on every render",\n'
        + "          );\n"
        + "        }\n"
        + "      }}\n"
        + "    >\n"
        + "      <QueryClientProvider client={client}>\n"
        + "        <Rendered {...props} />\n"
        + "      </QueryClientProvider>\n"
        + "    </Profiler>,\n"
        + "  );\n"
        + "  await act(async () => {\n"
        + "    await new Promise((resolve) => setTimeout(resolve, 200));\n"
        + "  });\n"
        + "  expect(errors).not.toHaveBeenCalled();\n"
        + "});\n"
    )
