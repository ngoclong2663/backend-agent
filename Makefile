-include .env
export

COMPOSE     := docker compose
API_DIR     := agent-api
UI_DIR      := agent-ui
PY          := $(CURDIR)/$(API_DIR)/.venv/bin

BGA_API_PORT   ?= 8100
BGA_UI_PORT    ?= 3100
BGA_PG_PORT    ?= 5442
BGA_REDIS_PORT ?= 6389
TEMPLATE_DIR   := $(CURDIR)/.data/fastapi-template
RUNNER_IMAGE   ?= bga-runner:1
RUNNER_NODE_IMAGE ?= bga-runner-node:1

# Antigravity's account login lives in the desktop keyring, which containers cannot reach. With
# ANTIGRAVITY_AUTH=account, `make up` also starts a worker on the host that runs only Antigravity jobs, and the
# Docker worker runs the other engines. Jobs are queued per engine, so each goes to a worker that can run it.
comma := ,
HOST_WORKER           := $(filter account,$(ANTIGRAVITY_AUTH))
DOCKER_WORKER_ENGINES := $(if $(HOST_WORKER),claude_code$(comma)claude_code_json$(comma)fake$(comma)gemini_api,)
HOST_WORKER_PID       := $(CURDIR)/.data/host-worker.pid
HOST_WORKER_LOG       := $(CURDIR)/.data/host-worker.log

# Host-side overrides for running api/worker/ui outside Docker.
DEV_ENV := DB_URL=postgresql+psycopg://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@localhost:$(BGA_PG_PORT)/$(POSTGRES_DB) \
           REDIS_URL=redis://localhost:$(BGA_REDIS_PORT)/0 \
           JWT_SECRET=$(JWT_SECRET) \
           CORS_ORIGINS=http://localhost:$(BGA_UI_PORT) \
           WORKSPACE_ROOT=$(HOST_WORKSPACE_ROOT) \
           WORKER_HEARTBEAT_FILE=$(CURDIR)/.data/worker.heartbeat \
           ENGINE_SKILLS_DIR=$(CURDIR)/.agents/skills \
           EXAMPLES_DIR=$(CURDIR)/examples \
           CLAUDE_CREDENTIALS_FILE=$(CLAUDE_CREDENTIALS_HOST_FILE) \
           TEMPLATE_DIR=$(TEMPLATE_DIR) \
           ARTIFACT_ROOT=$(CURDIR)/.data/artifacts \
           UPLOAD_ROOT=$(CURDIR)/.data/uploads \
           GEMINI_IMAGE_API_KEY=$(GEMINI_IMAGE_API_KEY) \
           GEMINI_API_KEY=$(GEMINI_API_KEY) \
           ANTIGRAVITY_AUTH=$(ANTIGRAVITY_AUTH) \
           IMAGE_PROVIDER=$(or $(IMAGE_PROVIDER),gemini) \
           VIDEO_PROVIDERS=$(VIDEO_PROVIDERS) YOUTUBE_API_KEY=$(YOUTUBE_API_KEY) PIXABAY_API_KEY=$(PIXABAY_API_KEY)

.PHONY: env up down down-all ps logs dev dev-down dev-api dev-worker dev-ui setup venv migrate test lint template runner runner-node frontend-base icon-index \
        host-worker host-worker-stop design-data design-diversity design-check-fixture design-check-app design-plugin-new design-plugin-check domain-new feature-new domain-check domain-report theme-report app-design-report app-design-proto kit-test sample-media video-keys

env:
	@test -f .env && echo ".env already exists" || ( \
	  sed -e "s|^JWT_SECRET=.*|JWT_SECRET=$$(openssl rand -hex 32)|" \
	      -e "s|^HOST_WORKSPACE_ROOT=.*|HOST_WORKSPACE_ROOT=$(CURDIR)/.data/workspaces|" \
	      .env.example > .env && mkdir -p .data/workspaces && echo "created .env" )

up: env runner runner-node $(if $(HOST_WORKER),template venv)
	@mkdir -p .data/artifacts .data/uploads
	$(COMPOSE) up -d --build --wait
	@$(MAKE) --no-print-directory $(if $(HOST_WORKER),host-worker,host-worker-stop)

# Worker on the host for Antigravity's account login (started by `make up`, stopped by `make down`).
host-worker: host-worker-stop
	@command -v $(or $(ANTIGRAVITY_BIN),agy) >/dev/null || echo "warning: agy not found on PATH; Antigravity will be unavailable"
	@nohup bash -c 'cd $(API_DIR) && exec env $(DEV_ENV) WORKER_ENGINES=antigravity$(comma)antigravity_json PREVIEW_WORKER=false $(PY)/python -u -m src.worker' > $(HOST_WORKER_LOG) 2>&1 & echo $$! > $(HOST_WORKER_PID)
	@echo "host worker (antigravity, antigravity_json) started: pid $$(cat $(HOST_WORKER_PID)), log .data/host-worker.log"

host-worker-stop:
	@if [ -f $(HOST_WORKER_PID) ]; then pid=$$(cat $(HOST_WORKER_PID)); \
	  kill $$pid 2>/dev/null && echo "host worker stopping" || true; \
	  for i in $$(seq 1 60); do kill -0 $$pid 2>/dev/null || break; sleep 0.5; done; \
	  if kill -0 $$pid 2>/dev/null; then echo "warning: host worker $$pid still running after 30 s"; \
	  else echo "host worker stopped"; fi; rm -f $(HOST_WORKER_PID); fi

# Sandbox image for validating generated projects (Story 6.1); its venv holds the overlay requirements and every
# plugin's (Story 10.2), so a project with plugins needs no install of its own.
runner:
	docker build -q -t $(RUNNER_IMAGE) -f docker/runner/Dockerfile \
	  --build-context runner_bin=docker/runner/bin --build-context plugins=$(API_DIR)/templates/plugins \
	  $(API_DIR)/templates/fastapi_overlay

# Sandbox image for generated frontends (Story 13.4): Node 22, pnpm, Playwright Chromium, a pnpm store pre-warmed
# from the pinned frontend base. `make frontend-base` regenerates that base (then review and rebuild this image).
runner-node:
	docker build -q -t $(RUNNER_NODE_IMAGE) -f docker/runner-node/Dockerfile $(API_DIR)/templates/nextjs_base

frontend-base:
	docker run --rm -v "$(CURDIR)/scripts/frontend-base.sh:/frontend-base.sh:ro" \
	  -v "$(CURDIR)/scripts/icon-index.mjs:/icon-index.mjs:ro" \
	  -v "$(CURDIR)/$(API_DIR)/templates/nextjs_base:/out" node:22-bookworm-slim sh /frontend-base.sh \
	  "$$(cd $(API_DIR) && $(PY)/python -c 'from src.modules.shared.domain.frontend_spec.catalogue import SHADCN_PRIMITIVES as P; print(" ".join(sorted(P)))')" \
	  "$$(cd $(API_DIR) && $(PY)/python -c 'from src.modules.shared.domain.frontend_spec.fonts import FONTS, JA_FONTS; print(" ".join(f.package for f in [*FONTS.values(), *JA_FONTS.values()]))')"
	cd $(API_DIR) && $(PY)/python -c 'import json; from src.orchestrator.frontend.scaffold import build_manifest, OVERLAY_DIR; \
	  (OVERLAY_DIR / "overlay.json").write_text(json.dumps(build_manifest(), indent=2, sort_keys=True) + "\n")'

# Only the icon index of the pinned base (Story 20.5; old Lucide names since 2026-11-04), without regenerating the base.
icon-index:
	docker run --rm -v "$(CURDIR)/scripts/icon-index.mjs:/icon-index.mjs:ro" \
	  -v "$(CURDIR)/$(API_DIR)/templates/nextjs_base:/out" -w /out node:22-bookworm-slim node /icon-index.mjs .

# UI UX Pro Max design data for drafted sites (Story 12.6), at a pinned commit: `make design-data COMMIT=<sha>`.
design-data:
	sh scripts/design-data.sh $(COMMIT)

# Design diversity report (Story 20.1): drafts examples/requirements/diversity with the fake engine and measures how
# different the designs are. ARGS="--screenshots" also builds each direction (Docker, runner-node image).
design-diversity: template
	cd $(API_DIR) && $(DEV_ENV) IMAGE_PROVIDER=none LANGSMITH_TRACING=false $(PY)/python -m scripts.design_diversity $(ARGS)

# The section library's design check (Stories 17.7, 20.2): the fixture in every preset, 390 / 768 / 1440 px, light
# and dark, measured against templates/nextjs_overlay/DESIGN_CHECKLIST.md (Docker, runner-node image).
design-check-fixture:
	cd $(API_DIR) && $(DEV_ENV) $(PY)/python -m scripts.design_check_fixture $(ARGS)

# The app kit's design check (Story 22.4): an app's screens at 375 / 1440 px, light and dark, on its mock API.
design-check-app:
	cd $(API_DIR) && $(DEV_ENV) $(PY)/python -m scripts.design_check_app $(ARGS)

# The video providers' keys (Epic 31): one cheap call each (YouTube videos.list, one Pixabay search).
video-keys:
	cd $(API_DIR) && $(DEV_ENV) $(PY)/python -m scripts.check_video_keys

# The generated apps' sample media (Story 29.2): made once with ffmpeg in a one-off container, then committed.
sample-media:
	sh scripts/sample-media.sh $(API_DIR)/templates/samples

# The app kit's own checks (Epic 28): type-check an app and run the kit's vitest files in the Node sandbox.
kit-test:
	cd $(API_DIR) && $(DEV_ENV) IMAGE_PROVIDER=none LANGSMITH_TRACING=false $(PY)/python -m scripts.kit_tests $(ARGS)

# Design plugins (Epic 30, Story 30.3): start one from its kind's starter; run the gates on one (Docker, runner-node).
#   make design-plugin-new KIND=card NAME=try
#   make design-plugin-check NAME=try [KIND=card] [ARGS="--fast"]
design-plugin-new:
	cd $(API_DIR) && $(DEV_ENV) IMAGE_PROVIDER=none $(PY)/python -m scripts.design_plugin new $(KIND) $(NAME)

design-plugin-check:
	cd $(API_DIR) && $(DEV_ENV) IMAGE_PROVIDER=none LANGSMITH_TRACING=false $(PY)/python -m scripts.design_plugin check $(NAME) $(if $(KIND),--kind $(KIND),) $(ARGS)

# Domain and feature plugins (Epic 33):
#   make domain-new NAME=socials | make feature-new NAME=comments | make domain-check [NAME=socials]
domain-new:
	cd $(API_DIR) && $(DEV_ENV) $(PY)/python -m scripts.domain_plugin new-domain $(NAME)
feature-new:
	cd $(API_DIR) && $(DEV_ENV) $(PY)/python -m scripts.domain_plugin new-feature $(NAME)
domain-check:
	cd $(API_DIR) && $(DEV_ENV) $(PY)/python -m scripts.domain_plugin check $(NAME)
# The domains' UX tasks on the recorded drafts (Story 33.1): make domain-report [ARGS=--baseline]
domain-report:
	cd $(API_DIR) && $(DEV_ENV) $(PY)/python -m scripts.domain_report $(ARGS)

# Epic 34: the reference apps' themes measured against the baseline: make theme-report [ARGS="--baseline" | "--html OUT"]
theme-report:
	cd $(API_DIR) && $(DEV_ENV) $(PY)/python -m scripts.theme_report $(ARGS)

# The app design report (Story 23.1; Story 30.1: signed in, fingerprints, edge similarity): the golden apps, no model call.
app-design-report:
	cd $(API_DIR) && $(DEV_ENV) IMAGE_PROVIDER=none LANGSMITH_TRACING=false $(PY)/python -m scripts.app_design_report $(ARGS)

# Story 23.0 prototype harness (dev tool): requirement → spec with a design brief → UI screenshots on the app kit.
# `draft` calls the Gemini API (paid); `build` and `page` make no model call. See scripts/app_design_proto/.
app-design-proto:
	cd $(API_DIR) && $(DEV_ENV) LANGSMITH_TRACING=false $(PY)/python -m scripts.app_design_proto $(ARGS)

# Local checkout of the pinned base template (the worker image bakes its own copy).
template:
	@. $(API_DIR)/templates/template.lock; \
	if [ "$$(git -C $(TEMPLATE_DIR) rev-parse HEAD 2>/dev/null)" != "$$commit" ]; then \
	  rm -rf $(TEMPLATE_DIR) && git clone -q --branch "$$branch" "$$repo" $(TEMPLATE_DIR) && \
	  git -C $(TEMPLATE_DIR) checkout -q "$$commit" && echo "template $$commit ready"; fi

# Preview containers are not part of the compose project: `down` stops them (they keep their data and come back
# with `start`), `down-all` removes every bga.* container, network, volume and image, previews included.
down: host-worker-stop
	$(COMPOSE) down
	@docker ps -q --filter label=bga.preview | xargs -r docker stop >/dev/null

down-all: host-worker-stop
	$(COMPOSE) down -v --remove-orphans
	@docker ps -aq --filter label=bga.preview | xargs -r docker rm -f >/dev/null
	@docker ps -aq --filter label=bga.sandbox | xargs -r docker rm -f >/dev/null
	@docker network ls -q --filter label=bga.preview | xargs -r docker network rm >/dev/null
	@docker network ls -q --filter label=bga.sandbox | xargs -r docker network rm >/dev/null
	@docker volume ls -q --filter name=bga-preview-db- | xargs -r docker volume rm >/dev/null
	@docker volume ls -q --filter label=bga.fe-modules | xargs -r docker volume rm >/dev/null
	@docker volume ls -q --filter name=bga-pnpm-store | xargs -r docker volume rm >/dev/null
	@docker images -q --filter label=bga.preview | xargs -r docker rmi -f >/dev/null

ps:
	$(COMPOSE) ps
	@if [ -f $(HOST_WORKER_PID) ] && kill -0 $$(cat $(HOST_WORKER_PID)) 2>/dev/null; then \
	  echo "host worker (antigravity): running, pid $$(cat $(HOST_WORKER_PID))"; fi

logs:
	$(COMPOSE) logs -f --tail=200

dev: env template runner runner-node
	$(COMPOSE) up -d --wait postgres redis

dev-down:
	$(COMPOSE) down

venv:
	@test -x $(PY)/python || ( cd $(API_DIR) && uv venv -q -p 3.12 .venv && \
	  uv pip install -q -p .venv/bin/python -r requirements-dev.txt )

setup: template venv
	cd $(UI_DIR) && pnpm install

dev-api:
	cd $(API_DIR) && $(DEV_ENV) $(PY)/fastapi dev src/main.py --port $(BGA_API_PORT)

dev-worker:
	cd $(API_DIR) && $(DEV_ENV) $(PY)/python -m src.worker

dev-ui:
	cd $(UI_DIR) && API_URL=http://localhost:$(BGA_API_PORT) pnpm dev --port $(BGA_UI_PORT)

migrate:
	cd $(API_DIR) && $(DEV_ENV) $(PY)/alembic upgrade head

test: template
	cd $(API_DIR) && $(DEV_ENV) IMAGE_PROVIDER=fake $(PY)/python -m pytest $(ARGS)

lint:
	cd $(API_DIR) && $(PY)/ruff check . && $(PY)/ruff format --check .
	cd $(UI_DIR) && pnpm lint
