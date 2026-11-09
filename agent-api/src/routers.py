from src.modules.auth.presenter import auth_router, me_router
from src.modules.engines.presenter import engine_router
from src.modules.evaluations.presenter import evaluation_router
from src.modules.generations.presenter import cache_router, generation_router
from src.modules.health.presenter import health_router
from src.modules.previews.presenter import integration_router, preview_router, previews_router
from src.modules.specs.presenter import (
    design_plugin_router,
    frontend_spec_router,
    spec_draft_router,
    spec_import_router,
    spec_router,
)
from src.modules.uploads.presenter import upload_router
from src.modules.usage.presenter import usage_router

all_router = [
    health_router,
    auth_router,
    me_router,
    spec_router,
    spec_import_router,
    frontend_spec_router,
    spec_draft_router,
    design_plugin_router,
    engine_router,
    cache_router,
    generation_router,
    preview_router,
    integration_router,
    evaluation_router,
    previews_router,
    usage_router,
    upload_router,
]
