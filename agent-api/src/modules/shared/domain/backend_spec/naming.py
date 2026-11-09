import keyword
import re

_IRREGULAR_PLURALS = {"person": "people", "child": "children", "man": "men", "woman": "women"}
_IRREGULAR_SINGULARS = {plural: singular for singular, plural in _IRREGULAR_PLURALS.items()}


def to_snake(name: str) -> str:
    value = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name)
    value = re.sub(r"(?<=[A-Z])([A-Z][a-z])", r"_\1", value)
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()


def py_name(name: str) -> str:
    """A snake-case name usable as a Python identifier: a keyword gets a trailing underscore (`class` → `class_`)."""
    return f"{name}_" if keyword.iskeyword(name) else name


def to_kebab(name: str) -> str:
    return to_snake(name).replace("_", "-")


def to_pascal(name: str) -> str:
    return "".join(part.capitalize() for part in to_snake(name).split("_") if part)


def to_camel(name: str) -> str:
    pascal = to_pascal(name)
    return pascal[:1].lower() + pascal[1:]


def pluralize(word: str) -> str:
    lower = word.lower()
    if lower in _IRREGULAR_PLURALS:
        return _IRREGULAR_PLURALS[lower]
    if re.search(r"[^aeiou]y$", lower):
        return word[:-1] + "ies"
    if re.search(r"(s|x|z|ch|sh)$", lower):
        return word + "es"
    return word + "s"


def singularize(word: str) -> str:
    lower = word.lower()
    if lower in _IRREGULAR_SINGULARS:
        return _IRREGULAR_SINGULARS[lower]
    if lower.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    if re.search(r"(sses|uses|xes|zzes|ches|shes)$", lower):
        return word[:-2]  # classes, statuses, boxes, buzzes, branches, dishes
    if re.search(r"(ses|zes)$", lower):
        return word[:-1]  # expenses, courses, cases, prizes
    if lower.endswith("s") and not lower.endswith("ss"):
        return word[:-1]
    return word


def table_name(entity_name: str) -> str:
    snake = to_snake(entity_name)
    head, _, last = snake.rpartition("_")
    return f"{head}_{pluralize(last)}" if head else pluralize(last)


# Epic 32: actions that record a person opening a record (a view counted, a watch logged). The screens run them once
# when the record opens; the access rules leave them to the record's readers, never its owner alone.
OPEN_WORDS = frozenset(
    {"view", "views", "watch", "watched", "play", "plays", "open", "opened", "read", "visit", "visited"}
)


def name_words(name: str) -> set[str]:
    """`VideoView` → {"video", "view"}; `recordView` → {"record", "view"}."""
    return {word.lower() for word in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", name)}


def is_open_action(op_id: str) -> bool:
    """`recipe.recordView`, `video.watch`: an operation named like a view of a record."""
    return bool(name_words(op_id.split(".", 1)[-1]) & OPEN_WORDS)
