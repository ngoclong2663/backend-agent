"""The design brief, completed by code (Epic 23, decision D1): the model chooses from the design space (archetype,
shell, a view per entity, field roles, home, filters, looks, areas); code checks every choice against the BackendSpec
and replaces what does not fit with the archetype's default, one note each (`design.replaced`). No model call.

Pure functions. `complete_design` runs inside `complete_outline` (before the contract is built: Epic 23 D6), so the
list features a view needs are added to the BackendSpec by `ensure_aggregates` (`design_list_features`).

Epic 30 (Story 30.2): the values are design plugins (`frontend_spec/design_registry.py`, `templates/design/`). Each
choice is checked against its descriptor's `needs` (one check per key, `_Data.lacks`) and falls back along the
descriptor's `fallback` chain, one note (D5). The archetype defaults below name plugins.
"""

import hashlib
import random
import re
from typing import Any

from pydantic import ValidationError

from src.modules.shared.domain.frontend_spec.app import MAX_META, AppDesign, AppLook
from src.modules.shared.domain.frontend_spec.design_registry import DesignPluginDescriptor, registry
from src.modules.shared.domain.frontend_spec.fonts import heading_kind_fits

from .recipes import first_recipe

ARCHETYPES: dict[str, dict[str, str]] = {
    # archetype → its frame and the main entity's default view
    "back-office": {"shell": "sidebar", "mobileNav": "drawer", "frame": "standard", "density": "compact",
                    "homeView": "dashboard", "view": "table"},
    "catalogue": {"shell": "topbar", "mobileNav": "bottom-tabs", "frame": "wide", "density": "comfortable",
                  "homeView": "catalogue", "view": "media-grid"},
    "feed": {"shell": "topbar", "mobileNav": "bottom-tabs", "frame": "narrow", "density": "comfortable",
             "homeView": "feed", "view": "feed"},
    "workspace": {"shell": "sidebar", "mobileNav": "drawer", "frame": "full", "density": "compact",
                  "homeView": "dashboard", "view": "board"},
    "booking": {"shell": "topbar-tabs", "mobileNav": "bottom-tabs", "frame": "standard", "density": "comfortable",
                "homeView": "agenda", "view": "calendar"},
    "learning": {"shell": "sidebar", "mobileNav": "bottom-tabs", "frame": "wide", "density": "comfortable",
                 "homeView": "dashboard", "view": "media-grid"},
    "storefront": {"shell": "topbar", "mobileNav": "bottom-tabs", "frame": "wide", "density": "comfortable",
                   "homeView": "catalogue", "view": "media-grid"},
}  # fmt: skip
DEFAULT_ARCHETYPE = "back-office"
# Words of a requirement → an archetype (Story 23.0: UI UX Pro Max's ranking alone matched "video library" to a
# component library, so these come first; whole words, counted).
ARCHETYPE_WORDS: dict[str, tuple[str, ...]] = {
    "feed": ("news", "feed", "blog", "posts", "articles", "community", "social", "magazine", "upvote"),
    "catalogue": ("video", "videos", "streaming", "channel", "music", "podcast", "gallery", "photos", "library",
                  "portfolio", "recipes", "browse"),
    "learning": ("course", "courses", "lesson", "lessons", "learner", "learners", "enrol", "enroll", "training",
                 "quiz", "students", "e-learning"),
    "storefront": ("shop", "store", "cart", "checkout", "products", "e-commerce", "ecommerce", "marketplace",
                   "orders", "buy"),
    "booking": ("booking", "bookings", "book", "appointment", "appointments", "reservation", "reservations",
                "schedule", "slots", "tickets", "rooms"),
    "workspace": ("tasks", "task", "project", "projects", "kanban", "sprint", "backlog", "pipeline", "deals"),
    "back-office": ("inventory", "admin", "crm", "invoices", "invoice", "accounting", "stock", "suppliers",
                    "employees", "reports"),
}  # fmt: skip
# A design key → the registry kind it names (the kit's dispatch reads the same keys)
KINDS = {"shell": "shell", "homeView": "home", "view": "list-view", "detailView": "detail-view",
         "filtersStyle": "filters", "card": "card", "fontPairing": "font-pairing"}  # fmt: skip
# a recipe's `prefers` key → the design key it breaks ties for (Story 30.7)
PREFERS = {"shell": "shell", "home": "homeView", "view": "view", "detail": "detailView", "filters": "filtersStyle",
           "card": "card", "density": "density"}  # fmt: skip
SCRIPT_OF_LOCALE = {"ja": "japanese"}  # a locale → the script a font pairing must cover (Story 30.6)
IMAGE_WORDS = ("image", "thumbnail", "cover", "logo", "banner", "avatar", "photo", "picture", "poster")
# Story 30.4: the aspect a card's media takes from the field's name
PORTRAIT_WORDS = ("poster", "bookcover", "jacket")
SQUARE_WORDS = ("cover", "album", "artwork", "logo", "avatar", "icon")
ASPECTS = ("wide", "portrait", "square", "auto")
CARD_VIEWS = (
    "cards",
    "media-grid",
    "shelves",
)  # the list views that draw cards (the registry's `cards` tag, Story 23.11)
MEDIA_TYPES = frozenset({"video", "audio"})  # Epic 29: a `media` role may be a player, not only an image
DURATION_WORDS = ("duration", "length", "runtime")
NUMERIC = frozenset({"integer", "float", "decimal"})
DATES = frozenset({"date", "datetime"})
HIDDEN = frozenset({"id", "allowedActions", "passwordHash", "password"})
# who keeps a shared field
ROLE_ORDER = ("title", "media", "avatar", "price", "stat", "duration", "badge", "subtitle", "meta")
CHIPS_MAX = 12  # values a row of chips shows
_WORD = re.compile(r"[a-z][a-z-]*")


def archetype_candidates(requirement: str, product_types: list[str] | None = None) -> list[str]:
    """Up to three archetypes for the prompt (Story 23.6): the requirement's words by count, then the product types'."""
    words = _WORD.findall(requirement.lower())
    scores = {name: sum(words.count(word) for word in hints) for name, hints in ARCHETYPE_WORDS.items()}
    out = [name for name, score in sorted(scores.items(), key=lambda kv: -kv[1]) if score > 0][:2]
    for product in product_types or []:
        for name, hints in ARCHETYPE_WORDS.items():
            if any(hint in product.lower() for hint in hints) and name not in out:
                out.append(name)
    return out[:3] or [DEFAULT_ARCHETYPE]


def archetype_for(requirement: str, product_types: list[str] | None = None) -> str:
    """The archetype a requirement's words point to (counted, ties in the table's order), else the ranked product
    types' names, else a back office."""
    words = _WORD.findall(requirement.lower())
    scores = {name: sum(words.count(word) for word in hints) for name, hints in ARCHETYPE_WORDS.items()}
    best = max(scores, key=lambda name: scores[name])
    if scores[best] > 0:
        return best
    for product in product_types or []:
        lower = product.lower()
        for name, hints in ARCHETYPE_WORDS.items():
            if any(hint in lower for hint in hints):
                return name
    return DEFAULT_ARCHETYPE


class _Data:
    """What the BackendSpec says about the entities a design may show."""

    def __init__(self, backend: dict[str, Any]):
        self.fields = {e["name"]: {f["name"]: f for f in e.get("fields") or []} for e in backend.get("entities") or []}
        self.lists: dict[str, dict[str, Any]] = {}
        for op in backend.get("operations") or []:
            if op.get("type") == "crud" and op.get("action") == "list" and op.get("entity") not in self.lists:
                self.lists[op["entity"]] = op
        self.flows = {
            (rule.get("entity"), (rule.get("params") or {}).get("field"))
            for rule in backend.get("rules") or []
            if rule.get("kind") == "transition"
        }
        self.roles = list((backend.get("auth") or {}).get("roles") or [])
        # a child's foreign key → its parent (shown by the parent's name: a bookmark titled by its post)
        self.references: dict[str, dict[str, str]] = {}
        for rel in backend.get("relationships") or []:
            if rel.get("foreignKey") and rel.get("type") in ("one-to-many", "many-to-one", "one-to-one"):
                child, parent = (
                    (rel["to"], rel["from"]) if rel.get("type") != "many-to-one" else (rel["from"], rel["to"])
                )
                self.references.setdefault(child, {})[rel["foreignKey"]] = parent

    def image(self, entity: str, name: str) -> bool:
        field = self.fields[entity].get(name) or {}
        return field.get("type") in ("image", "file") or (
            field.get("type") == "string" and any(word in name.lower() for word in IMAGE_WORDS)
        )

    def media(self, entity: str, name: str) -> bool:
        """Epic 29: what may play the `media` role: an image, or a video / audio file (shown by the kit's players)."""
        return self.image(entity, name) or self.kind(entity, name) in MEDIA_TYPES

    def duration(self, entity: str, name: str) -> bool:
        kind = self.kind(entity, name)
        return kind in MEDIA_TYPES or (kind in NUMERIC and any(w in name.lower() for w in DURATION_WORDS))

    def first_duration(self, entity: str, skip: set[str]) -> str | None:
        return next((n for n in self.fields[entity] if n not in skip and self.duration(entity, n)), None)

    def kind(self, entity: str, name: str | None) -> str | None:
        return (self.fields[entity].get(name or "") or {}).get("type")

    def first_image(self, entity: str, skip: set[str]) -> str | None:
        return next(
            (n for n in self.fields[entity] if n not in skip and "avatar" not in n.lower() and self.image(entity, n)),
            None,
        )

    def first_media(self, entity: str, skip: set[str]) -> str | None:
        """Epic 29: a video or audio field comes first (the record is the media), else the first image."""
        played = next((n for n in self.fields[entity] if n not in skip and self.kind(entity, n) in MEDIA_TYPES), None)
        return played or self.first_image(entity, skip)

    def status(self, entity: str, wanted: str | None) -> str | None:
        """A board's column field: the named enum, else one with a status flow, else one called status."""
        enums = [n for n, f in self.fields[entity].items() if f.get("type") == "enum"]
        if wanted in enums:
            return wanted
        flowing = [n for n in enums if (entity, n) in self.flows]
        return next(iter(flowing), "status" if "status" in enums else None)

    def date(self, entity: str, wanted: str | None) -> str | None:
        """A calendar's date: the named one, else the first date that is not a bookkeeping timestamp."""
        dates = [n for n, f in self.fields[entity].items() if f.get("type") in DATES]
        if wanted in dates:
            return wanted
        return next((n for n in dates if n not in ("createdAt", "updatedAt")), None)

    def end(self, entity: str, start: str) -> str | None:
        dates = [n for n, f in self.fields[entity].items() if f.get("type") in DATES and n != start]
        return next((n for n in dates if re.search(r"end|until|finish|to$", n, re.IGNORECASE)), None)

    def filter_fields(self, entity: str) -> list[str]:
        """The list's filters a row of chips or a facet panel can show: enums and references (`…Id`)."""
        op = self.lists.get(entity) or {}
        out = []
        for name in op.get("filters") or []:
            kind = self.kind(entity, name)
            if kind == "enum" or (kind == "uuid" and name.endswith("Id")) or kind == "boolean":
                out.append(name)
        return out

    def aspect(self, entity: str, media: str | None) -> str:
        """A card's media aspect from the field's name: a poster is portrait, a cover or an album is square."""
        lower = (media or "").lower()
        if any(word in lower for word in PORTRAIT_WORDS):
            return "portrait"
        if any(word in lower for word in SQUARE_WORDS):
            return "square"
        return "wide"

    def group(self, entity: str, wanted: str | None) -> str | None:
        """A field to group records by (shelves): the named enum or parent, else the first enum, else a parent."""
        fields = self.fields[entity]
        parents = self.references.get(entity, {})
        if wanted and (fields.get(wanted, {}).get("type") == "enum" or wanted in parents):
            return wanted
        enums = [n for n, f in fields.items() if f.get("type") == "enum" and (entity, n) not in self.flows]
        return next(iter(enums), next(iter(parents), None))

    def children(self, entity: str) -> list[str]:
        return [child for child, parents in self.references.items() if entity in parents.values()]

    def long_text(self, entity: str) -> str | None:
        return next((n for n, f in self.fields[entity].items() if f.get("type") == "text"), None)

    def featured(self, entity: str) -> str | None:
        """What picks a featured record: a `featured` boolean, else a date to sort by."""
        flagged = next(
            (n for n, f in self.fields[entity].items() if f.get("type") == "boolean" and "featur" in n), None
        )
        return flagged or self.date(entity, None) or ("createdAt" if "createdAt" in self.fields[entity] else None)

    def lacks(self, entity: str | None, need: str, roles: dict[str, Any], raw: dict[str, Any]) -> str | None:
        """Why the entity does not meet a plugin's need (Epic 30, D5), or None when it does."""
        if entity is None or entity not in self.fields:
            return "an entity" if need == "mainList" else f"an entity for {need}"
        media = roles.get("media")
        if need == "mediaField":
            return None if media else "an image, a video or an audio field"
        if need == "imageField":
            has = (roles.get("avatar") or (media and self.image(entity, media))) or self.first_image(entity, set())
            return None if has else "an image field"
        if need == "playableField":
            return None if self.kind(entity, media) in MEDIA_TYPES else "a video or an audio field"
        if need == "statusFlow":
            return None if self.status(entity, raw.get("groupBy") or roles.get("badge")) else "a status field"
        if need == "dateField":
            first_meta = next(iter(roles.get("meta") or []), None)
            return None if self.date(entity, raw.get("dateField") or first_meta) else "a date field"
        if need == "dateSort":
            return None if self.date(entity, None) or "createdAt" in self.fields[entity] else "a date to sort by"
        if need == "groupField":
            return (
                None
                if self.group(entity, raw.get("groupBy") or roles.get("badge"))
                else "a category or a parent to group by"
            )
        if need == "enumOrReferenceFilter":
            return None if self.filter_fields(entity) else "a filter on a status, a category or a parent"
        if need == "search":
            return None if (self.lists.get(entity) or {}).get("search") else "a search on the list"
        if need == "mainList":
            return None if entity in self.lists else f"a list of {entity}"
        if need == "parentOrChildren":
            return None if self.references.get(entity) or self.children(entity) else "a parent or children"
        if need == "longTextField":
            return None if self.long_text(entity) else "a long text field"
        if need == "featured":
            return None if self.featured(entity) else "a featured flag or a date"
        return f"an unknown need {need}"

    def fits(self, entity: str, role: str, name: str) -> str | None:
        """Why a field cannot play a role, or None when it can."""
        if name not in self.fields[entity] or name in HIDDEN:
            return "no such field"
        kind = self.kind(entity, name)
        if role == "media" and not self.media(entity, name):
            return f"a {kind} field is not an image, a video or an audio file"
        if role == "avatar" and not self.image(entity, name):
            return f"a {kind} field is not an image"
        if role == "duration" and not self.duration(entity, name):
            return f"a {kind} field is not a duration"
        if role in ("stat", "price") and kind not in NUMERIC:
            return f"a {kind} field is not a number"
        if role == "title" and kind not in ("string", "text") and name not in self.references.get(entity, {}):
            return f"a {kind} field is not a name"
        return None


def _list_of(value: Any) -> list[Any]:
    """Seen live (Story 23.0): models write a list of one as a plain value."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _items(value: Any) -> dict[str, Any]:
    """A design's entities, keyed by entity (the schema's list, or an object keyed by entity as Gemini wrote it)."""
    if isinstance(value, dict):
        return {k: v for k, v in value.items() if isinstance(v, dict)}
    out = {}
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict) and isinstance(item.get("entity"), str):
            out[item["entity"]] = {k: v for k, v in item.items() if k != "entity"}
    return out


def _enum(value: Any, allowed: tuple[str, ...] | frozenset[str] | list[str]) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def _label(kind: str, name: str) -> str:
    plugin = registry().get(kind, name)
    return f"{plugin.label.lower()} ({name})" if plugin and plugin.label.lower() != name else name


class _Completion:
    def __init__(
        self, data: _Data, where: str, rng: random.Random | None = None, prefers: dict[str, str] | None = None
    ):
        self.data = data
        self.where = where
        self.replaced: list[str] = []
        self.rng = rng  # Story 30.7 (D9): picks among equal candidates for the axes the brief left open
        self.prefers = prefers or {}  # the first look's recipe `prefers`: a tie-breaker, never a rule
        self.archetype: str | None = None
        self.main: str | None = None

    def note(self, message: str) -> None:
        self.replaced.append(f"{self.where}{message}")

    def roles(self, entity: str, raw: Any) -> dict[str, Any]:
        raw = raw if isinstance(raw, dict) else {}
        out: dict[str, Any] = {}
        used: dict[str, str] = {}
        order = sorted(raw.items(), key=lambda kv: ROLE_ORDER.index(kv[0]) if kv[0] in ROLE_ORDER else len(ROLE_ORDER))
        for role, value in order:
            if role not in ROLE_ORDER:
                self.note(f"{entity}: '{role}' is not a field role; left out")
                continue
            kept = []
            for name in _list_of(value):
                if not isinstance(name, str):
                    continue
                if name in used:
                    self.note(f"{entity}: {role} '{name}' left out (already the {used[name]})")
                    continue
                problem = self.data.fits(entity, role, name)
                if problem:
                    self.note(f"{entity}: {role} '{name}' left out ({problem})")
                    continue
                kept.append(name)
                used[name] = role
            if kept:
                out[role] = kept[:MAX_META] if role == "meta" else kept[0]
        if "media" not in out:
            image = self.data.first_media(entity, set(used))
            if image:
                out["media"] = image
                used[image] = "media"
        if "duration" not in out and self.data.kind(entity, out.get("media")) in MEDIA_TYPES:
            duration = self.data.first_duration(entity, set(used) | {out["media"]})
            if duration and self.data.kind(entity, duration) in NUMERIC:
                out["duration"] = duration
        return out

    def candidates(self, kind: str, entity: str | None, roles: dict[str, Any], raw: dict[str, Any]) -> list[str]:
        """Story 30.7: the ready plugins of a kind offered for the archetype whose `needs` the contract meets."""
        out = []
        for plugin in registry().candidates(kind, self.archetype):
            if not any(self.data.lacks(entity, need, roles, raw) for need in plugin.needs):
                out.append(plugin.name)
        return out

    def open_pick(
        self, key: str, default: str | None, entity: str | None, roles: dict[str, Any], raw: dict[str, Any]
    ) -> str | None:
        """An axis the brief left open (Story 30.7): the first look's preference when it is a candidate, else the
        seed's pick among the candidates (the archetype default is one of them), else the default."""
        if self.rng is None:
            return default
        picks = self.candidates(KINDS[key], entity, roles, raw)
        if not picks:
            return default
        preferred = next((v for k, v in self.prefers.items() if PREFERS.get(k) == key), None)
        if preferred in picks:
            return preferred
        if default in picks and len(picks) == 1:
            return default
        return self.rng.choice(picks)

    def choose(
        self,
        key: str,
        raw: dict[str, Any],
        default: str | None,
        entity: str | None,
        roles: dict[str, Any],
        where: str = "",
        open_choice: bool = False,
    ) -> str | None:
        """One axis (Epic 30, D5): the drafted plugin when it is one of the kind's ready plugins, else the default
        (`open_choice`: the seed's pick among the candidates, Story 30.7); then down the descriptor's fallback chain
        until every `needs` is met, one note per step."""
        kind = KINDS[key]
        reg = registry()
        wanted = raw.get(key)
        value = _enum(wanted, reg.names(kind))
        if wanted is not None and value is None:
            self.note(f"{where}{key} '{wanted}' is not one of the {kind} plugins; {default or 'none'} used")
        if wanted is None and open_choice:
            default = self.open_pick(key, default, entity, roles, raw)
        start = value or default
        if start is None:
            return None
        missing_of = ""
        for name in reg.fallback_chain(kind, start):
            plugin: DesignPluginDescriptor = reg.plugins[kind][name]
            missing = [m for m in (self.data.lacks(entity, need, roles, raw) for need in plugin.needs) if m]
            if not missing:
                if name != start:
                    self.note(
                        f"{where}{_label(kind, start)} needs {missing_of or 'its data'}; shown as {_label(kind, name)}"
                    )
                return name
            if name == start:
                missing_of = " and ".join(missing)
        self.note(f"{where}no {kind} plugin fits; {start} kept")  # the registry guarantees a chain ends in no needs
        return start

    def entity(self, entity: str, raw: dict[str, Any], default_view: str) -> dict[str, Any]:
        roles = self.roles(entity, raw.get("roles"))
        where = f"{entity}: "
        main = entity == self.main  # the seed and the look's preferences shape the main entity's screens (30.7)
        view = self.choose("view", raw, default_view, entity, roles, where, open_choice=main) or default_view
        out: dict[str, Any] = {}
        if view == "board":
            out["groupBy"] = self.data.status(entity, raw.get("groupBy") or roles.get("badge"))
        elif "groupField" in registry().plugins["list-view"][view].needs:
            out["groupBy"] = self.data.group(entity, raw.get("groupBy") or roles.get("badge"))
        if "dateField" in registry().plugins["list-view"][view].needs:
            day = self.data.date(entity, raw.get("dateField") or next(iter(roles.get("meta") or []), None))
            out["dateField"] = day
            end = raw.get("endField") if self.data.kind(entity, raw.get("endField")) in DATES else None
            end = end or self.data.end(entity, day)
            if end:
                out["endField"] = end
        detail_default = None
        if raw.get("detailView") is None and self.data.kind(entity, roles.get("media")) == "video":
            # Epic 29 (Story 29.5): a video record opens on its player; Story 30.5: on a watch page when the entity has
            # a list to draw "Up next" from (the watch plugin falls back to `media` where its needs are not met)
            detail_default = (
                "watch" if entity in self.data.lists and "watch" in registry().names("detail-view") else "media"
            )
        detail = self.choose("detailView", raw, detail_default, entity, roles, where, open_choice=main)
        filters = self.choose("filtersStyle", raw, None, entity, roles, where, open_choice=main)
        # Story 30.4: the card anatomy (a record without media reads text first), its aspect from the media field's
        # name (a poster is portrait, a cover or an album square) and the grid's columns
        card_default = ("stacked" if roles.get("media") else "text-first") if view in CARD_VIEWS else None
        card = (
            self.choose("card", raw, card_default, entity, roles, where, open_choice=main)
            if registry().names("card")
            else None
        )
        out |= {"view": view, "roles": roles}
        if detail:
            out["detailView"] = detail
        if filters:
            out["filtersStyle"] = filters
        if card:
            out["card"] = card
            aspect = _enum(raw.get("aspect"), ASPECTS) or self.data.aspect(entity, roles.get("media"))
            if raw.get("aspect") is not None and raw.get("aspect") not in ASPECTS:
                self.note(f"{where}aspect '{raw.get('aspect')}' is not one of {list(ASPECTS)}; {aspect} used")
            if aspect != "wide":
                out["aspect"] = aspect
            columns = raw.get("columns")
            if isinstance(columns, int) and not isinstance(columns, bool):
                clamped = min(6, max(2, columns))
                if clamped != columns:
                    self.note(f"{where}columns {columns} clamped to {clamped}")
                out["columns"] = clamped
            elif columns is not None:
                self.note(f"{where}columns '{columns}' is not a number; the view's own used")
        return out

    def default_view(self, entity: str, main: str | None, archetype: str) -> str:
        if entity == main:
            return ARCHETYPES[archetype]["view"]
        if self.data.first_media(entity, set()):
            return "cards"
        return "table"

    def layout(self, raw: dict[str, Any], inherited: dict[str, Any] | None = None) -> dict[str, Any]:
        """One layout (the app's, or an area's): archetype, frame, home, main entity and the entities' views."""
        inherited = inherited or {}
        archetype = _enum(raw.get("archetype"), tuple(ARCHETYPES)) or inherited.get("archetype")
        if raw.get("archetype") is not None and archetype != raw.get("archetype"):
            self.note(f"archetype '{raw.get('archetype')}' is not one of the archetypes")
        archetype = archetype or DEFAULT_ARCHETYPE
        self.archetype = archetype
        defaults = ARCHETYPES[archetype]
        out: dict[str, Any] = {"archetype": archetype}
        out["shell"] = self.choose("shell", raw, defaults["shell"], None, {}, open_choice=True) or defaults["shell"]
        for key, allowed in (
            ("mobileNav", ("drawer", "bottom-tabs")),
            ("frame", ("narrow", "standard", "wide", "full")),
            ("density", ("compact", "comfortable", "spacious")),
        ):
            value = _enum(raw.get(key), allowed)
            if raw.get(key) is not None and value is None:
                self.note(f"{key} '{raw.get(key)}' is not allowed; {defaults[key]} used")
            if key == "density" and value is None:
                if self.prefers.get("density") in allowed:
                    out[key] = self.prefers["density"]  # Story 30.7: the look's density, a tie-breaker
                continue  # else the theme's density (an axis apps had before Epic 23) unless the brief sets one
            out[key] = value or defaults[key]
        entities = self.data.fields
        main = raw.get("mainEntity") if raw.get("mainEntity") in entities else None
        if raw.get("mainEntity") is not None and main is None:
            self.note(f"main entity '{raw.get('mainEntity')}' is not in the BackendSpec")
        listed = [name for name in entities if name in self.data.lists]
        main = main or inherited.get("mainEntity") or next(iter(listed), next(iter(entities), None))
        out["mainEntity"] = main
        self.main = main
        drafted = _items(raw.get("entities"))
        for name in sorted(set(drafted) - set(entities)):
            self.note(f"entity '{name}' is not in the BackendSpec; left out")
        views = {}
        for name in entities:
            if name not in self.data.lists and name not in drafted:
                continue  # no list: nothing to present
            views[name] = self.entity(name, drafted.get(name) or {}, self.default_view(name, main, archetype))
        out["entities"] = views
        main_view = views.get(main or "", {})
        home = self.choose(
            "homeView", raw, defaults["homeView"], main, main_view.get("roles") or {}, "home: ", open_choice=True
        )
        out["homeView"] = home or defaults["homeView"]
        if "dateField" in registry().plugins["home"][out["homeView"]].needs and "dateField" not in main_view:
            main_view["dateField"] = self.data.date(main, None)  # the agenda's day (checked by `lacks`)
        return out


REQUESTED: dict[str, tuple[str, ...] | None] = {  # None: a #rrggbb colour
    "accent": None,
    "background": None,
    "text": None,
    "scheme": ("light", "dark"),
    "headingFont": ("serif", "sans", "geometric", "rounded", "display", "mono"),
    "corners": ("sharp", "rounded", "pill"),
    "photos": ("prominent",),
}


def _requested(raw: Any, completion: _Completion) -> dict[str, Any] | None:
    """What the requirement says about the look (`AppRequestedStyle`): the values that fit, a note for each other."""
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {}
    for key, allowed in REQUESTED.items():
        value = raw.get(key)
        if value is None:
            continue
        if allowed is None:
            fits = isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value) is not None
            value = value.lower() if fits else value
        else:
            fits = _enum(value, allowed) is not None
        if fits:
            out[key] = value
        else:
            completion.note(f"requested {key} '{value}' is not one of the values; left out")
    if out and isinstance(raw.get("words"), str):
        out["words"] = raw["words"][:200]
    return out or None


def _looks(raw: Any, completion: _Completion) -> list[dict[str, Any]]:
    out = []
    for item in _list_of(raw):
        recipe = item.get("recipe") if isinstance(item, dict) else item
        try:
            look = AppLook.model_validate(
                {"recipe": recipe, "reason": (item or {}).get("reason") if isinstance(item, dict) else None}
            )
        except ValidationError:
            completion.note(f"look '{recipe}' is not a recipe; left out")
            continue
        if all(look.recipe != kept["recipe"] for kept in out):
            out.append(look.model_dump(by_alias=True, exclude_none=True))
    return out[:3]


def design_seed(text: str) -> int:
    """Story 30.7 (D9): the draft's seed, from the requirement's words: the same requirement gives the same design."""
    return int(hashlib.sha256(text.strip().encode()).hexdigest()[:8], 16)


def _prefers(raw_looks: Any) -> dict[str, str]:
    """The first drafted look's recipe `prefers` (Story 30.7): the tie-breakers for the open axes."""
    for item in _list_of(raw_looks):
        recipe = item.get("recipe") if isinstance(item, dict) else item
        plugin = registry().get("recipe", recipe if isinstance(recipe, str) else None)
        if plugin is not None:
            return dict(plugin.prefers)
    return {}


def pairing_candidates(locale: str | None, requested: dict[str, Any] | None, archetype: str | None) -> list[str]:
    """Story 30.6: the font pairings an app may take: covering its script (a Japanese app needs a pairing that sets
    Japanese), of the requested kind of heading face (Story 23.13), offered for the archetype."""
    script = SCRIPT_OF_LOCALE.get((locale or "en")[:2])
    kind = (requested or {}).get("headingFont")
    out = []
    for plugin in registry().candidates("font-pairing", archetype):
        if script and script not in plugin.scripts:
            continue
        if kind and not heading_kind_fits(kind, plugin.heading):
            continue
        out.append(plugin.name)
    return out


def assign_pairings(design: dict[str, Any], locale: str | None, seed: int | None = None) -> list[str]:
    """Story 30.6: a font pairing per look (one suited to the look's recipe, the three looks using at least two
    pairings) and the app's (`fontPairing`: the brief's when it fits, else the first look's). Returns the notes."""
    notes: list[str] = []
    candidates = pairing_candidates(locale, design.get("requested"), design.get("archetype"))
    if not candidates:
        return notes
    rng = random.Random(seed if seed is not None else 0)
    chosen = design.get("fontPairing")
    if chosen is not None and chosen not in candidates:
        reason = "does not set this app's script" if SCRIPT_OF_LOCALE.get((locale or "en")[:2]) else "does not fit"
        notes.append(f"font pairing '{chosen}' {reason}; the looks' own used")
        chosen = None
    used: list[str] = []
    for look in design.get("looks") or []:
        suited = [
            n for n in candidates if look["recipe"] in registry().plugins["font-pairing"][n].recipes
        ] or candidates
        fresh = [n for n in suited if n not in used] or suited
        pick = chosen if chosen in suited and not used else (fresh[0] if seed is None else rng.choice(fresh))
        look["fontPairing"] = pick
        used.append(pick)
    if len(set(used)) < 2 and len(candidates) > 1 and len(used) > 1:
        other = next(n for n in candidates if n != used[0])
        design["looks"][-1]["fontPairing"] = other
        notes.append(
            f"look '{design['looks'][-1]['recipe']}' set in '{other}': three looks in one type offer no choice"
        )
    design["fontPairing"] = chosen or (design["looks"][0]["fontPairing"] if design.get("looks") else candidates[0])
    return notes


def complete_design(
    raw: Any,
    raw_areas: Any,
    backend: dict[str, Any],
    archetype_hint: str | None = None,
    seed: int | None = None,
    locale: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """The drafted brief (any JSON, or none) → a complete design, the areas and the replacements. `archetype_hint`
    (code's pick from the requirement) is used when the brief names none. `seed` (Story 30.7, D9) picks among equal
    candidates for the axes the brief left open; without one the archetype defaults apply, as before."""
    data = _Data(backend)
    raw = raw if isinstance(raw, dict) else {}
    rng = random.Random(seed) if seed is not None else None
    app = _Completion(data, "", rng, _prefers(raw.get("looks")))
    if archetype_hint and not raw.get("archetype"):
        raw = {**raw, "archetype": archetype_hint}
    design = app.layout(raw)
    design["looks"] = _looks(raw.get("looks"), app)
    requested = _requested(raw.get("requested"), app)
    if requested:
        design["requested"] = requested
    if seed is not None:
        design["seed"] = seed
    pairing = _enum(raw.get("fontPairing"), registry().names("font-pairing"))
    if raw.get("fontPairing") is not None and pairing is None:
        app.note(f"fontPairing '{raw.get('fontPairing')}' is not one of the font pairings; left out")
    if pairing is not None:
        design["fontPairing"] = pairing
    if isinstance(raw.get("reason"), str):
        design["reason"] = raw["reason"][:300]
    areas: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, area in enumerate(_list_of(raw_areas)):
        if not isinstance(area, dict):
            continue
        ident = re.sub(r"[^a-z0-9-]+", "-", str(area.get("id") or f"area-{index + 1}").lower()).strip("-") or "area"
        where = _Completion(data, f"area '{ident}': ", rng, app.prefers)
        roles = [r for r in _list_of(area.get("roles")) if isinstance(r, str)]
        own = [r for r in roles if r in data.roles and r not in seen]
        for role in roles:
            if role not in own:
                where.note(f"role '{role}' " + ("is in another area" if role in seen else "is not a role of the app"))
        if not own:
            where.note("left out (no role of its own)")
            app.replaced += where.replaced
            continue
        seen.update(own)
        layout = where.layout(area.get("design") if isinstance(area.get("design"), dict) else area, design)
        areas.append(
            {
                "id": ident,
                "label": str(area.get("label") or ident.replace("-", " ").capitalize())[:40],
                "roles": own,
                "prefix": "/" if not areas else f"/{ident}",
                "design": layout,
            }
        )
        app.replaced += where.replaced
    if areas:
        for role in data.roles:
            if role not in seen:
                app.note(f"role '{role}' is in no area; it uses the first area ({areas[0]['id']})")
                areas[0]["roles"].append(role)
    if len(areas) == 1:
        app.note("one area is the app itself; areas left out")
        areas = []
    signup = data.roles[0] if data.roles else None
    if areas and signup and signup not in areas[0]["roles"]:  # sign-up lands in the first area, at `/`
        home = next(index for index, area in enumerate(areas) if signup in area["roles"])
        app.note(f"area '{areas[home]['id']}' moved first: sign-up gives the role '{signup}'")
        areas.insert(0, areas.pop(home))
    for index, area in enumerate(areas):
        area["prefix"] = "/" if index == 0 else f"/{area['id']}"
    design["replaced"] = app.replaced
    AppDesign.model_validate(design)  # a bug here, not a bad draft: every value was checked above
    return design, areas, app.replaced


def design_choices(archetypes: list[str] | None = None) -> dict[str, str]:
    """The prompt's choice lists (Epic 30, Story 30.2; 30.7: only the candidates for the ranked archetypes, so the
    prompt does not grow with the registry): kind → "`name` (when to choose it), …"."""
    from src.modules.shared.domain.frontend_spec.design_registry import KINDS, registry

    out: dict[str, str] = {}
    for kind in KINDS:
        seen: dict[str, str] = {}
        for archetype in archetypes or [None]:
            for name, choose in registry().choices(kind, archetype):
                seen.setdefault(name, choose)
        ordered = [name for name in registry().names(kind) if name in seen]
        out[kind] = ", ".join(f"`{name}` ({seen[name].rstrip('.')})" for name in ordered)
    return out


def design_notes(replaced: list[str]) -> list[dict[str, Any]]:
    """The replacements as draft notes (on `/app/design`)."""
    return [{"spec": "frontend", "path": "/app/design", "message": line, "suggestion": None} for line in replaced]


def home_entity(design: dict[str, Any]) -> str | None:
    """The entity whose list is the home page, or None for the dashboard (`homeView` dashboard or bento)."""
    plugin = registry().get("home", design.get("homeView"))
    if plugin is not None and "mainList" in plugin.needs:
        return design.get("mainEntity")
    return None


KIT_DEFAULTS = {"archetype": DEFAULT_ARCHETYPE, "shell": "sidebar", "mobileNav": "drawer", "frame": "standard",
                "homeView": "dashboard", "entities": {}, "looks": []}  # fmt: skip


def kit_design(outline: dict[str, Any]) -> dict[str, Any]:
    """What the kit reads (`app.json` `design`): the outline's design, or today's kit for an app drafted before Epic 23
    (a sidebar, the dashboard home, the outline's list styles)."""
    design = outline.get("design") or {}
    out = {**KIT_DEFAULTS, **{k: v for k, v in design.items() if k not in ("replaced", "reason", "requested")}}
    out["recipe"] = first_recipe(design) if design else None  # Story 23.7: the look on screen
    if not out.get("mainEntity"):
        out["mainEntity"] = next(iter(outline.get("entities") or {}), None)
    return out


def _layouts(outline: dict[str, Any]) -> list[dict[str, Any]]:
    """The app's design and each area's: every layout whose views need list features."""
    design = outline.get("design") or {}
    return [design, *[(area.get("design") or {}) for area in outline.get("areas") or []]]


def list_features(
    backend: dict[str, Any], operations: list[dict[str, Any]], outline: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Epic 23 D6: what the views need from the lists, added to the BackendSpec before the contract is built: a date
    range on the list of an entity shown on a calendar or an agenda (Story 23.4), a sort by its date on a feed's list
    (newest first, 23.3). Each change is checked by the validator; one that would make the spec invalid is skipped
    with a note. Returns the operations and notes."""
    from src.modules.shared.domain.backend_spec import validate_spec_data

    notes: list[dict[str, Any]] = []
    out = [dict(op) for op in operations]
    lists = {op.get("entity"): op for op in out if op.get("type") == "crud" and op.get("action") == "list"}
    fields = {e["name"]: {f["name"]: f for f in e.get("fields") or []} for e in backend.get("entities") or []}
    for layout in _layouts(outline):
        for entity, view in (layout.get("entities") or {}).items():
            op = lists.get(entity)
            if op is None:
                continue
            change: dict[str, Any] = {}
            day = view.get("dateField")
            if day and day not in (op.get("ranges") or []):
                change["ranges"] = [*(op.get("ranges") or []), day]
            if day and day not in (op.get("sort") or []):  # a calendar opens on the nearest month, an agenda in order
                change["sort"] = [*(op.get("sort") or []), day]
            featured_home = layout.get("homeView") == "featured" and entity == layout.get("mainEntity")
            if view.get("view") == "feed" or featured_home:  # Story 30.5: a featured home shows the newest first
                dated = next(
                    (m for m in [*(view.get("roles") or {}).get("meta", []), "publishedAt", "createdAt"]
                     if (fields.get(entity, {}).get(m) or {}).get("type") in DATES),
                    None,
                )  # fmt: skip
                if dated and dated not in (op.get("sort") or []):
                    change["sort"] = [*(op.get("sort") or []), dated]
            if not change:
                continue
            trial = {**backend, "operations": [o if o is not op else {**op, **change} for o in out]}
            if not validate_spec_data(trial).report.valid:
                notes.append(
                    {"spec": "backend", "path": "/operations", "message": f"{op['operationId']}: {change} would not "
                     "validate; the view loads its first page", "suggestion": None}
                )  # fmt: skip
                continue
            op.update(change)
            what = ", ".join(f"{key} {value[-1]}" for key, value in change.items())
            notes.append(
                {"spec": "backend", "path": "/operations", "message": f"{op['operationId']} gained {what} for its "
                 f"{view.get('view')} view (Epic 23)", "suggestion": None}
            )  # fmt: skip
    return out, notes
