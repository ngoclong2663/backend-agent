from .autofix import autofix_frontend_spec
from .catalogue import BUILTIN_SECTIONS, SHADCN_PRIMITIVES, THEME_PRESETS
from .fonts import FONTS, closest_font, font_category, font_imports
from .issues import FrontendIssueCode
from .normalizer import iter_sections, normalize_frontend_spec, page_id, route_params, walk_sections
from .registry import (
    FRONTEND_SPEC_MODELS,
    LATEST_FRONTEND_SPEC_VERSION,
    frontend_spec_json_schema,
    supported_frontend_versions,
)
from .schema_v1 import FrontendSpecV1
from .section_props import LAYOUT_SECTIONS, MAX_DEPTH, SECTION_ITEMS, SECTION_PROPS
from .validator import (
    FrontendValidationResult,
    route_matches,
    route_refs,
    validate_frontend_spec_data,
    validate_frontend_spec_text,
)

__all__ = [
    "autofix_frontend_spec",
    "BUILTIN_SECTIONS",
    "FONTS",
    "FRONTEND_SPEC_MODELS",
    "FrontendIssueCode",
    "FrontendSpecV1",
    "FrontendValidationResult",
    "LAYOUT_SECTIONS",
    "MAX_DEPTH",
    "SECTION_ITEMS",
    "SECTION_PROPS",
    "LATEST_FRONTEND_SPEC_VERSION",
    "SHADCN_PRIMITIVES",
    "THEME_PRESETS",
    "closest_font",
    "font_category",
    "font_imports",
    "frontend_spec_json_schema",
    "iter_sections",
    "normalize_frontend_spec",
    "page_id",
    "route_matches",
    "route_params",
    "route_refs",
    "supported_frontend_versions",
    "validate_frontend_spec_data",
    "validate_frontend_spec_text",
    "walk_sections",
]
