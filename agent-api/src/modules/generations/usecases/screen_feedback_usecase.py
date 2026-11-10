"""Epic 33 (Story 33.14): a comment on a generated app's screen becomes a change of its choices (or a request)."""

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends

from src.configs import config
from src.engines.llm import LlmError, LlmProvider
from src.engines.registry import get_llm_provider
from src.libs.exceptions import NotFoundException, ServiceUnavailableException
from src.modules.generations.ports.output import IArtifactRepoDep
from src.modules.generations.usecases.artifact_usecases import artifact_file
from src.modules.generations.usecases.get_generation_usecase import GetGenerationUsecaseDep
from src.modules.shared.domain.entities import UserEntity
from src.orchestrator.feedback import ANSWER_SCHEMA, apply_feedback, prompt

REQUESTS_FILE = "plugin-requests.jsonl"  # under ARTIFACT_ROOT: what no plugin could do, for the maintainers

LlmProviderDep = Annotated[LlmProvider, Depends(get_llm_provider)]


def requests_path() -> Path:
    return Path(config.artifact_root) / REQUESTS_FILE


class ScreenFeedbackUsecase:
    def __init__(self, getter: GetGenerationUsecaseDep, artifact_repo: IArtifactRepoDep, provider: LlmProviderDep):
        self.getter, self.artifact_repo, self.provider = getter, artifact_repo, provider

    async def execute(self, generation_id: str, user: UserEntity, target: str | None, comment: str) -> dict[str, Any]:
        generation = self.getter.load(generation_id, user)
        artifact = self.artifact_repo.find_by_name(generation_id, "frontend-spec.json")
        if artifact is None:
            raise NotFoundException("This generation has no frontend to change")
        spec = json.loads(artifact_file(artifact).read_text())
        try:
            with tempfile.TemporaryDirectory() as state_dir:
                answer = await self.provider.json(
                    "screen_feedback", prompt(spec, target, comment), ANSWER_SCHEMA, state_dir=Path(state_dir)
                )
        except LlmError as exc:
            raise ServiceUnavailableException("The feedback could not be read; try again") from exc
        result = apply_feedback(spec, answer.data if isinstance(answer.data, dict) else {})
        if result["outcome"] in ("request", "data") and (result["request"] or comment):
            domain = ((spec.get("app") or {}).get("domain") or {}).get("name")
            record = {
                "at": datetime.now(UTC).isoformat(),
                "generationId": generation_id,
                "domain": domain,
                "types": ((spec.get("app") or {}).get("domain") or {}).get("types") or {},
                "target": target,
                "comment": comment,
                "request": result["request"],
                "outcome": result["outcome"],
            }
            path = requests_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a") as out:
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"generationId": generation.id, "target": target, "comment": comment, **result}


def plugin_requests(limit: int = 200) -> list[dict[str, Any]]:
    """The latest requests no plugin could answer, newest first (grouped by the UI per domain and type)."""
    path = requests_path()
    if not path.is_file():
        return []
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return list(reversed(rows))[:limit]


ScreenFeedbackUsecaseDep = Annotated[ScreenFeedbackUsecase, Depends(ScreenFeedbackUsecase)]
