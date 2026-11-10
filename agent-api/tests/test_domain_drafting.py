"""Epic 33 (Story 33.6): the domain a requirement describes, offered to `draft_app@v10` and checked by code."""

import json
from pathlib import Path

from src.engines.prompts import PromptLibrary
from src.modules.shared.domain.backend_spec import validate_spec_data
from src.modules.shared.domain.frontend_spec.app import outline_schema
from src.orchestrator.drafting.domains import apply_domain, offered, rank_domains

FIXTURES = Path(__file__).parent / "fixtures"
REQUIREMENTS = FIXTURES / "domains" / "requirements"
DRAFT = FIXTURES / "drafts" / "domain-socials"


def test_code_ranks_the_socials_domain_for_the_socials_requirement_only():
    assert [d.name for d in rank_domains((REQUIREMENTS / "socials.md").read_text())] == ["socials"]
    for other in ("news", "learning", "drivers", "iot"):
        assert "socials" not in [d.name for d in rank_domains((REQUIREMENTS / f"{other}.md").read_text())]
    assert rank_domains("A tool to track invoices for a plumbing company") == []


def _outline(**domain):
    return {"design": {"mainEntity": "Clip"}, "domain": {"name": "socials", **domain}}


def test_the_domain_answer_merges_its_features_into_the_draft():
    backend = json.loads((DRAFT / "backend-spec.json").read_text())
    merged, block, notes = apply_domain(backend, _outline(roles={"content": "Clip"}))
    assert block == {"name": "socials", "roles": {"content": "Clip"}, "types": {}, "features": []}
    assert {"ClipComment", "ClipReaction"} <= {e["name"] for e in merged["entities"]}
    assert notes[0]["message"] == "Built on the Socials domain"
    assert validate_spec_data(merged).report.valid


def test_a_role_the_model_left_out_is_found_by_its_words():
    backend = json.loads((DRAFT / "backend-spec.json").read_text())
    _, block, _ = apply_domain(backend, _outline())
    assert block["roles"] == {"content": "Clip"}


def test_an_answer_that_does_not_hold_keeps_the_generic_flow():
    backend = json.loads((DRAFT / "backend-spec.json").read_text())
    assert apply_domain(backend, {"design": {}})[1] is None  # no domain named
    same, block, notes = apply_domain(backend, {"domain": {"name": "shipping"}})
    assert block is None and same is backend and "not available" in notes[0]["message"]
    no_post = {**backend, "entities": [e for e in backend["entities"] if e["name"] != "Clip"]}
    _, block, notes = apply_domain(no_post, {"design": {}, "domain": {"name": "socials"}})
    assert block is None and "kept generic" in notes[0]["message"]


def test_the_v10_prompt_adds_the_domain_block_only_when_a_domain_is_offered():
    library = PromptLibrary()
    source = (library.root / "draft_app" / "v10.md").read_text()
    piece = source[source.index("{% if domains %}") : source.index("## Areas")]
    shown = library.env.from_string(piece).render(
        domains=offered(rank_domains((REQUIREMENTS / "socials.md").read_text()))
    )
    assert "`socials`:" in shown and "Brings: Comments (" in shown and "`content` (Post)" in shown
    assert library.env.from_string(piece).render(domains=[]).strip() == ""
    v9 = (library.root / "draft_app" / "v9.md").read_text()
    assert source[source.index("# Task") :].replace(piece, "") == v9[v9.index("# Task") :]  # otherwise v9's text


def test_only_the_v10_schema_shows_the_domain():
    assert "domain" not in outline_schema(True)["properties"]
    assert "domain" in outline_schema(True, domain=True)["properties"]
