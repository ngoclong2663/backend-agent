"""Epic 33 (Story 33.3): scaffold and check domain and feature plugins.

python -m scripts.domain_plugin new-domain <name>
python -m scripts.domain_plugin new-feature <name>
python -m scripts.domain_plugin check [<domain>]
"""

import json
import sys

from src.modules.shared.domain.domains.registry import DOMAINS_DIR, FEATURES_DIR, NAME, DomainRegistry

DOMAIN_STARTER = {
    "status": "draft",
    "choose": "When the requirement describes …",
    "words": [],
    "roles": {"content": {"label": "Content", "words": [], "needs": []}},
    "areas": [{"id": "people", "label": "People", "people": ["member"], "pattern": "back-office"}],
    "features": {"required": [], "optional": []},
}
FEATURE_STARTER = {
    "status": "draft",
    "attachesTo": "content",
    "choose": "When people …",
    "spec": {"entities": [], "relationships": [], "operations": [], "rules": [], "policies": []},
    "computed": [],
    "kit": {"components": [], "slots": []},
}


def _new(folder, name: str, file: str, starter: dict) -> int:
    if not NAME.match(name):
        print(f"'{name}' is not a plugin name (lowercase letters, digits and hyphens)")
        return 1
    path = folder / name / file
    if path.exists():
        print(f"{path} already exists")
        return 1
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"name": name, "label": name.replace("-", " ").title(), **starter}, indent=2) + "\n")
    print(f"wrote {path} (status draft: offered only with BGA_DESIGN_INCLUDE_DRAFTS=1)")
    return 0


def _check(only: str | None) -> int:
    reg = DomainRegistry()
    for problem in reg.problems:
        print("problem:", problem)
    for name, domain in reg.domains.items():
        if only and name != only:
            continue
        types = ", ".join(reg.types.get(name, {})) or "none"
        uses = [u.feature for u in [*domain.features.required, *domain.features.optional]]
        print(f"{name} ({domain.status}): types {types}; features {', '.join(uses) or 'none'}")
    if only and only not in reg.domains:
        print(f"no domain '{only}'")
        return 1
    return 1 if reg.problems else 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "new-domain":
        return _new(DOMAINS_DIR, argv[1], "domain.json", DOMAIN_STARTER)
    if len(argv) >= 2 and argv[0] == "new-feature":
        return _new(FEATURES_DIR, argv[1], "feature.json", FEATURE_STARTER)
    if argv and argv[0] == "check":
        return _check(argv[1] if len(argv) > 1 else None)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
