"""Epic 33 (Story 33.3): domain, type and feature plugins.

A domain says what a kind of product must have (its core entities by role, its areas and people, its features); a type
is one way to lay a domain's areas out (pages and slots); a feature is full-stack behaviour shared by domains
(comments with replies, reactions with state, dispatch, telemetry). Each is a folder with a JSON descriptor:

    templates/domains/<domain>/domain.json
    templates/domains/<domain>/types/<type>/type.json
    templates/features/<feature>/feature.json

Like the design registry (Epic 30): a broken folder is recorded in `problems` and left out, so one draft in progress
never breaks generation; `strict=True` (the tooling, the tests) raises instead. `BGA_DESIGN_INCLUDE_DRAFTS=1` counts
draft plugins in (docs/development/test-doubles.md).
"""

import json
import logging
import os
import re
from functools import cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TEMPLATES = Path(__file__).resolve().parents[5] / "templates"
DOMAINS_DIR = TEMPLATES / "domains"
FEATURES_DIR = TEMPLATES / "features"
NAME = re.compile(r"^[a-z][a-z0-9-]*$")
ROLE = re.compile(r"^[a-z][a-zA-Z0-9]*$")
Status = Literal["ready", "draft"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CoreRole(_Model):
    """A core entity of the domain, played by one drafted entity (`content` = Clip). `needs` are field roles the
    entity must have (`title`, `media`, `author`, `status`, `time`, `parent`), checked on the draft (Story 33.6)."""

    label: str = Field(min_length=1, max_length=60)
    words: list[str] = []  # entity names that usually play it (`post`, `clip`, `video`), for the hint and the check
    needs: list[str] = []
    person: bool = False  # played by the signed-in user's entity (a member, a driver)


class DomainArea(_Model):
    id: str = Field(pattern=NAME.pattern, max_length=40)
    label: str = Field(min_length=1, max_length=60)
    people: list[str] = Field(min_length=1)  # role words matched against the BackendSpec's roles
    pattern: str = "back-office"  # an Epic 32 pattern
    main: str | None = None  # the core role the area is about


class FeatureUse(_Model):
    feature: str = Field(pattern=NAME.pattern)
    on: str | None = None  # the core role it attaches to; None: the feature's own `attachesTo`
    options: dict[str, Any] = {}


class DomainFeatures(_Model):
    required: list[FeatureUse] = []
    optional: list[FeatureUse] = []


class DomainDescriptor(_Model):
    name: str = Field(pattern=NAME.pattern, max_length=40)
    label: str = Field(min_length=1, max_length=60)
    status: Status = "draft"
    order: int = 100
    choose: str = Field(min_length=1, max_length=400)  # when it fits, shown to the model
    words: list[str] = Field(min_length=1)  # requirement words that point to it, for code's ranking
    roles: dict[str, CoreRole] = Field(min_length=1)
    areas: list[DomainArea] = Field(min_length=1)
    features: DomainFeatures = DomainFeatures()


class TypeSection(_Model):
    slot: str = Field(pattern=NAME.pattern)
    bind: dict[str, Any] = {}  # role or field bindings (`{"role": "content"}`, `{"feature": "comments"}`)
    options: dict[str, Any] = {}


class TypePage(_Model):
    id: str = Field(pattern=NAME.pattern, max_length=60)
    title: str = Field(min_length=1, max_length=80)
    route: str = Field(pattern=r"^/[a-z0-9\-/\[\]]*$")
    menu: bool = False
    icon: str | None = None
    sections: list[TypeSection] = []


class TypeArea(_Model):
    pages: list[TypePage] = Field(min_length=1)
    shell: str | None = None
    home: str | None = None  # the page id of the area's home


class TypeTask(_Model):
    id: str = Field(pattern=NAME.pattern)
    role: str
    goal: str
    budget: int | None = None
    check: dict[str, Any]


class TypeDescriptor(_Model):
    name: str = Field(pattern=NAME.pattern, max_length=40)
    label: str = Field(min_length=1, max_length=60)
    status: Status = "draft"
    order: int = 100
    choose: str = Field(min_length=1, max_length=400)
    areas: dict[str, TypeArea] = {}  # keyed by the domain's area id
    tasks: list[TypeTask] = []


class FeatureComputed(_Model):
    """A read-only field the feature adds to its target's responses, computed by the backend and the mocks."""

    field: str = Field(min_length=1)  # may use `{kind}` / `{Kind}`: one field per value of the `kinds` option
    kind: Literal["count", "mine"]  # count: rows pointing at the record; mine: the caller's row id, or null
    entity: str  # the feature's entity holding the rows (placeholders allowed: `{Target}Reaction`)
    key: str  # its foreign key to the target (`{target}Id`)
    where: dict[str, Any] = {}  # equality filters (`{"kind": "like"}`)
    owner: str | None = None  # `mine`: the owner field compared with the caller


class FeatureKit(_Model):
    components: list[str] = []  # files under the feature's frontend/files, registered for its slots
    slots: list[str] = []


class FeatureDescriptor(_Model):
    name: str = Field(pattern=NAME.pattern, max_length=40)
    label: str = Field(min_length=1, max_length=60)
    status: Status = "draft"
    attaches_to: str = Field(alias="attachesTo")  # a core role name, `person`, or `app` (attached once)
    choose: str = Field(min_length=1, max_length=400)
    options: dict[str, Any] = {}  # option name -> {"default", "values", "help"}
    spec: dict[str, Any] = {}  # a BackendSpec fragment with placeholders ({Target}, {target}, {Person}, …)
    computed: list[FeatureComputed] = []
    kit: FeatureKit = FeatureKit()
    replaces: list[str] = []  # drafted entity words the feature takes over (`comment`, `like`), dropped with a note
    uses: list[str] = []  # other features it needs


class DomainRegistryError(ValueError):
    pass


class DomainRegistry:
    def __init__(self, templates: Path = TEMPLATES, strict: bool = False) -> None:
        self.domains: dict[str, DomainDescriptor] = {}
        self.types: dict[str, dict[str, TypeDescriptor]] = {}
        self.features: dict[str, FeatureDescriptor] = {}
        self.problems: list[str] = []
        for path in sorted((templates / "features").glob("*/feature.json")):
            feature = self._load(path, FeatureDescriptor, templates)
            if feature is not None and self._named(path, feature.name, path.parts[-2], templates):
                self.features[feature.name] = feature
        for path in sorted((templates / "domains").glob("*/domain.json")):
            if path.parts[-2].startswith("_"):
                continue
            domain = self._load(path, DomainDescriptor, templates)
            if domain is None or not self._named(path, domain.name, path.parts[-2], templates):
                continue
            missing = [
                use.feature
                for use in [*domain.features.required, *domain.features.optional]
                if use.feature not in self.features
            ]
            if missing:
                self.problems.append(f"domains/{domain.name}: feature '{missing[0]}' is missing")
                continue
            bad_roles = [
                use.on
                for use in [*domain.features.required, *domain.features.optional]
                if use.on and use.on not in domain.roles and use.on not in ("person", "app")
            ]
            if bad_roles:
                self.problems.append(f"domains/{domain.name}: feature attached to unknown role '{bad_roles[0]}'")
                continue
            self.domains[domain.name] = domain
            self.types[domain.name] = {}
            for type_path in sorted(path.parent.glob("types/*/type.json")):
                kind = self._load(type_path, TypeDescriptor, templates)
                if kind is None or not self._named(type_path, kind.name, type_path.parts[-2], templates):
                    continue
                unknown = [area for area in kind.areas if area not in {a.id for a in domain.areas}]
                if unknown:
                    self.problems.append(f"domains/{domain.name}/types/{kind.name}: unknown area '{unknown[0]}'")
                    continue
                self.types[domain.name][kind.name] = kind
        if self.problems and strict:
            raise DomainRegistryError("domain plugins: " + "; ".join(self.problems))

    def _load(self, path: Path, model: type[BaseModel], root: Path) -> Any:
        try:
            return model.model_validate(json.loads(path.read_text()))
        except (ValueError, json.JSONDecodeError) as exc:
            self.problems.append(f"{path.relative_to(root)}: {exc}")
            return None

    def _named(self, path: Path, name: str, folder: str, root: Path) -> bool:
        if name != folder:
            self.problems.append(f"{path.relative_to(root)}: name '{name}' does not match its folder")
            return False
        return True

    # -- lookups ----------------------------------------------------------------------------------------------------

    @staticmethod
    def _offered(status: str) -> bool:
        return status == "ready" or os.environ.get("BGA_DESIGN_INCLUDE_DRAFTS") == "1"

    def ready_domains(self) -> list[DomainDescriptor]:
        return sorted((d for d in self.domains.values() if self._offered(d.status)), key=lambda d: (d.order, d.name))

    def ready_types(self, domain: str) -> list[TypeDescriptor]:
        return sorted(
            (t for t in self.types.get(domain, {}).values() if self._offered(t.status)), key=lambda t: (t.order, t.name)
        )

    def domain(self, name: str | None) -> DomainDescriptor | None:
        found = self.domains.get(name or "")
        return found if found is not None and self._offered(found.status) else None

    def type(self, domain: str, name: str | None) -> TypeDescriptor | None:
        found = self.types.get(domain, {}).get(name or "")
        return found if found is not None and self._offered(found.status) else None

    def feature(self, name: str) -> FeatureDescriptor | None:
        found = self.features.get(name)
        return found if found is not None and self._offered(found.status) else None


@cache
def registry() -> DomainRegistry:
    loaded = DomainRegistry()
    for problem in loaded.problems:
        logging.getLogger(__name__).warning("domain plugin left out: %s", problem)
    return loaded
