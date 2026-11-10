"""An engine run that died on the network or the provider's API runs once more, in the same workdir."""

import asyncio

import pytest

from src.configs import config
from src.engines import EngineResult, EngineStatus
from src.engines.cli_engine import is_network_failure
from src.engines.fake_engine import FakeEngine, demo_scenario
from src.engines.prompts import PromptRef, RenderedPrompt
from src.orchestrator.context import EngineFailure
from tests.test_prewarm_dependencies import _build_test_ctx, _submit
from workflow_helpers import runner_ctx

# agy's result error when its last model call dropped (gen_01M71JYQKMT8VB0JHNNWSQ7TEW, the `search_queries` module:
# its files and summary were written, the run still ended in ERROR)
AGY_DROPPED = (
    'API error (attempt 1): request failed: Post "https://daily-cloudcode-pa.googleapis.com/v1internal:'
    'streamGenerateContent?alt=sse": read tcp [2402:800::1]:50490->[2001:4860::]:443: read: operation timed out'
)
# agy's stderr when headless mode auto-denied a read outside the workdir (gen_01M71HE13TKW67RGD9HEE1JVV0)
AGY_DENIED = (
    'jetski: no output produced — a tool required the "read_file" permission that headless mode cannot prompt for, '
    "so it was auto-denied."
)
PROMPT = RenderedPrompt(ref=PromptRef(id="complete_backend", version="v5", sha256="0" * 64), text="complete it")


def _failed(message: str | None, reason: str = "crash", status=EngineStatus.CLI_ERROR) -> EngineResult:
    return EngineResult(
        invocation_id="x",
        engine="antigravity",
        purpose="complete_backend",
        status=status,
        error_reason=reason,
        error_message=message,
        duration_ms=1,
    )


def test_a_dropped_model_call_is_a_network_failure():
    assert is_network_failure(_failed(AGY_DROPPED))
    assert is_network_failure(_failed("upstream answered 503 Service Unavailable"))


@pytest.mark.parametrize(
    "result",
    [
        _failed(AGY_DENIED),  # the run's own doing: a rerun would do it again
        _failed("Traceback: KeyError 'id'"),
        _failed(None),
        _failed("authentication failed or timed out", reason="auth"),
        _failed("print timeout reached", reason="timeout", status=EngineStatus.TIMEOUT),
    ],
)
def test_other_failures_are_not(result):
    assert not is_network_failure(result)


class _DropsOnce(FakeEngine):
    """Fails its first `complete_backend` run as agy does when a model call drops, then answers."""

    def __init__(self, root, message):
        super().__init__(root, demo_scenario(0))
        self.message = message
        self.workdirs = []

    async def run(self, request, on_event=None):
        if request.purpose != "complete_backend":
            return await super().run(request, on_event)
        self.workdirs.append(request.workdir)
        if len(self.workdirs) == 1:
            return _failed(self.message).model_copy(update={"invocation_id": request.invocation_id})
        return EngineResult(
            invocation_id=request.invocation_id,
            engine=self.name,
            purpose=request.purpose,
            status=EngineStatus.OK,
            duration_ms=1,
        )


def _run(client, login, tmp_path, engine):
    generation_id = _submit(client, login)

    async def go():
        async with runner_ctx(tmp_path, engine=engine) as runner:
            ctx = _build_test_ctx(runner, generation_id, engine, None)
            scratch = ctx.workspace.root / "scratch" / "module-x"
            scratch.mkdir(parents=True)
            return await ctx.run_engine("generate_backend", "complete_backend", PROMPT, workdir_override=scratch)

    return asyncio.run(go())


def test_a_network_failure_runs_again_in_the_same_workdir(client, login, tmp_path):
    engine = _DropsOnce(tmp_path, AGY_DROPPED)
    result = _run(client, login, tmp_path, engine)
    assert result.ok
    assert len(engine.workdirs) == 2 and engine.workdirs[0] == engine.workdirs[1]


def test_a_second_network_failure_fails(client, login, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "engine_network_retries", 0)
    engine = _DropsOnce(tmp_path, AGY_DROPPED)
    with pytest.raises(EngineFailure):
        _run(client, login, tmp_path, engine)
    assert len(engine.workdirs) == 1


def test_a_denied_permission_is_not_retried(client, login, tmp_path):
    engine = _DropsOnce(tmp_path, AGY_DENIED)
    with pytest.raises(EngineFailure):
        _run(client, login, tmp_path, engine)
    assert len(engine.workdirs) == 1
