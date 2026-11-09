"""What a FrontendSpec may name without declaring it: built-in section components, shadcn primitives and the
theme presets the normalizer fills in (Story 12.1). The frontend planner (13.1) reads the same tables."""

from typing import Any

# Built-in section components → the shadcn primitives they are built from.
BUILTIN_SECTIONS: dict[str, dict[str, Any]] = {
    "ActionBar": {"uses": ["button", "alert-dialog"], "description": "Bar of action buttons for operations"},
    "Hero": {"uses": ["button"], "description": "Heading, text, image and a call to action"},
    "Features": {"uses": ["card"], "description": "Grid of feature cards"},
    "CallToAction": {"uses": ["button"], "description": "Banner with one primary action"},
    "Testimonials": {"uses": ["card", "avatar"], "description": "Quotes with author"},
    "Faq": {"uses": ["accordion"], "description": "Questions and answers"},
    "Pricing": {"uses": ["card", "badge", "button"], "description": "Plans side by side"},
    "Stats": {"uses": ["card"], "description": "Key numbers"},
    "Gallery": {"uses": ["aspect-ratio"], "description": "Image grid"},
    # Epic 31: videos people watch (a featured one, or a grid), only when the requirement has something to watch
    "Video": {"uses": [], "description": "A featured video, or a grid of two to six videos, each credited"},
    "RichText": {"uses": [], "description": "Formatted text block"},
    "ContactInfo": {"uses": ["card"], "description": "Address, e-mail, phone, map link"},
    # Story 20.8: sections for what businesses really have, so pages follow the requirement, not a landing template.
    "Steps": {"uses": [], "description": "How it works, step by step (booking, ordering, a service)"},
    "Timeline": {"uses": [], "description": "A story over time: history, milestones, a programme"},
    "Team": {"uses": ["avatar"], "description": "The people, with role, short bio and photo"},
    "PriceList": {"uses": [], "description": "A menu or price list in groups"},
    "Location": {"uses": ["card"], "description": "Address, opening hours, phone and a map link"},
    "Comparison": {"uses": ["card"], "description": "Options side by side in a table"},
    "Statement": {"uses": [], "description": "One statement or real quote, set large"},
    "Form": {"uses": ["field", "input", "textarea", "select", "checkbox", "button"], "description": "A form"},
    "CardGrid": {"uses": ["card", "badge", "pagination"], "description": "Records as cards"},
    "DataTable": {"uses": ["table", "pagination", "input", "select"], "description": "Records as a table"},
    "DetailView": {"uses": ["card", "badge", "separator"], "description": "One record"},
    "List": {"uses": ["item", "pagination"], "description": "Records as a list"},
    # Layout nodes (Story 17.1): arrange the sections in `children`.
    "Columns": {"uses": [], "description": "Child sections side by side", "layout": True},
    "Stack": {"uses": [], "description": "Child sections one under another", "layout": True},
    "Grid": {"uses": [], "description": "Child sections in a responsive grid", "layout": True},
    "Tabs": {"uses": ["tabs"], "description": "One tab per child section", "layout": True},
}

SHADCN_PRIMITIVES = frozenset(
    {
        "accordion", "alert", "alert-dialog", "aspect-ratio", "avatar", "badge", "breadcrumb", "button",
        "button-group", "calendar", "card", "carousel", "chart", "checkbox", "collapsible", "command",
        "context-menu", "dialog", "drawer", "dropdown-menu", "empty", "field", "hover-card", "input",
        "input-group", "input-otp", "item", "kbd", "label", "menubar", "navigation-menu", "pagination", "popover",
        "progress", "radio-group", "resizable", "scroll-area", "select", "separator", "sheet", "sidebar",
        "skeleton", "slider", "sonner", "spinner", "switch", "table", "tabs", "textarea", "toggle", "toggle-group",
        "tooltip",
    }
)  # fmt: skip

THEME_PRESETS: dict[str, dict[str, Any]] = {
    "minimal": {
        "colors": {
            "primary": "#18181b",
            "secondary": "#f4f4f5",
            "accent": "#2563eb",
            "background": "#ffffff",
            "foreground": "#09090b",
            "muted": "#f4f4f5",
            "destructive": "#dc2626",
        },
        "typography": {"headingFont": "Inter", "bodyFont": "Inter"},
        "radius": "md",
        "density": "comfortable",
    },
    "editorial": {
        "colors": {
            "primary": "#1c1917",
            "secondary": "#f5f0e8",
            "accent": "#b45309",
            "background": "#fdfbf7",
            "foreground": "#1c1917",
            "muted": "#f5f0e8",
            "destructive": "#b91c1c",
        },
        "typography": {"headingFont": "Playfair Display", "bodyFont": "Source Serif 4"},
        "radius": "sm",
        "density": "comfortable",
    },
    "playful": {
        "colors": {
            "primary": "#7c3aed",
            "secondary": "#fce7f3",
            "accent": "#f59e0b",
            "background": "#fffbf5",
            "foreground": "#1e1b4b",
            "muted": "#f5f3ff",
            "destructive": "#e11d48",
        },
        "typography": {"headingFont": "Poppins", "bodyFont": "Nunito"},
        "radius": "lg",
        "density": "comfortable",
    },
    "corporate": {
        "colors": {
            "primary": "#1d4ed8",
            "secondary": "#e2e8f0",
            "accent": "#0891b2",
            "background": "#ffffff",
            "foreground": "#0f172a",
            "muted": "#f1f5f9",
            "destructive": "#dc2626",
        },
        "typography": {"headingFont": "IBM Plex Sans", "bodyFont": "IBM Plex Sans"},
        "radius": "sm",
        "density": "comfortable",
    },
    "dashboard": {
        "colors": {
            "primary": "#2563eb",
            "secondary": "#f1f5f9",
            "accent": "#10b981",
            "background": "#f8fafc",
            "foreground": "#0f172a",
            "muted": "#f1f5f9",
            "destructive": "#dc2626",
        },
        "typography": {"headingFont": "Inter", "bodyFont": "Inter"},
        "radius": "md",
        "density": "compact",
    },
}

DEFAULT_STATES = {"loading": "Loading…", "empty": "Nothing here yet", "error": "Could not load the data"}
