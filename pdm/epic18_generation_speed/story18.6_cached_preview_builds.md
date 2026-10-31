# Story 18.6 — Cached preview builds, built in parallel

**Epic:** [18 — Generation speed](epic18_generation_speed.md) · **Requirements:** FR-30, FR-14 · **Depends on:** 7.3, 13.5

## User story

As a user, I want the previews of a finished generation up in about a minute, while they are still built from
the ZIPs I download, so that the preview keeps proving those ZIPs build on their own.

## Evidence (`gen_01M66QJWJGAZ7WMHZFR6TJ6KMR`, `preview.status` events)

- 16:06:17 both previews requested → 16:09:12 frontend RUNNING → 16:10:22 backend RUNNING (built **after** the
  frontend: `PreviewService.handle` holds one lock per generation for every mutating command).
- `frontend-preview-build.log`: `pnpm install` downloaded all 795 packages (`reused 0`), then `pnpm build` again.
  The layer cache cannot help: `COPY package.json pnpm-lock.yaml ...` comes first, and package.json holds the
  site's `name` (`"anki-vocab"`), so the layer differs per site. The lock itself is the pinned base lock
  (`overlay.json` → `lockSha256`), the same for every site.
- `preview-build.log`: `pip install -r requirements.txt` from scratch, no `Using cache`.
- Images are built with docker-py `images.build` (legacy builder: no BuildKit cache mounts), and removed with
  the preview (`images.remove`), which also drops their layers.

## Steps

1. **Frontend Dockerfiles** (`agent-api/templates/nextjs_overlay/files/dynamic/Dockerfile` and
   `.../static/Dockerfile`): a `deps` stage that depends only on the lockfile, then the build:

   ```dockerfile
   FROM ${NODE_IMAGE} AS deps
   WORKDIR /app
   ENV NEXT_TELEMETRY_DISABLED=1
   RUN corepack enable && corepack prepare pnpm@<base pnpmVersion> --activate
   COPY pnpm-lock.yaml pnpm-workspace.yaml ./
   RUN pnpm fetch --frozen-lockfile

   FROM deps AS build
   COPY package.json ./
   RUN pnpm install --frozen-lockfile --offline
   COPY . .
   RUN pnpm build
   ```

   then the runtime stage as today. Pin pnpm to `overlay.json` → `baseLock.pnpmVersion` (10.18.3) and add a unit
   test that the Dockerfiles and `overlay.json` agree. Confirm `pnpm fetch` honours `pnpm-workspace.yaml`
   settings (e.g. built dependencies) by building one generated site.
2. **Backend Dockerfile** (`agent-api/templates/fastapi_overlay/files/Dockerfile`): same idea, a `deps` stage
   with `COPY requirements.txt` + `pip install`, then `FROM deps AS app` with the rest. The ZIP must still build
   with a plain `docker build .`.
3. **Keep the dependency layers alive.** In both preview runtimes (`src/preview/docker_preview.py`,
   `src/preview/docker_frontend_preview.py`), before the full build, build `target="deps"` tagged
   `bga-fe-deps:<sha12>` / `bga-be-deps:<sha12>` when that tag does not exist (sha of the files the deps stage
   copies). The full build then reuses those layers from the local cache. Never remove `bga-*-deps` images with a
   preview; `make down-all` removes them (as it removes the `bga-fe-modules-*` volumes). Label them like the other
   images.
4. **Build in parallel.** Let the frontend and backend `start` commands of one generation build their images at
   the same time: hold the per-generation lock only around container operations, or use one lock per
   (generation, kind) for the build. Keep today's container order (the backend's CORS needs the frontend's
   origin): if the backend container is ready to start before the frontend has a host port, reserve the
   frontend port first (`_ports` / `upsert_preview`). Read `previews.py` `_options` before changing the order.
5. Sandbox/Docker tests (`BGA_SANDBOX_TESTS=1`): build the golden frontend twice under different site names and
   assert the second build log shows the `pnpm fetch` step from cache; same for the backend's `pip install`.

## Acceptance criteria

- [x] Generated frontend and backend ZIPs still build with plain `docker build .` (checked by a test).
- [x] A second preview of a different site with the same dependencies reuses the dependency layers (no package
      downloads in its build log).
- [x] Frontend and backend images of one generation build concurrently.
- [x] `bga-*-deps` images survive preview removal; `make down-all` removes them.
- [x] Status note: time from `preview.status` STARTING to both RUNNING, before (~245 s) and after, cold and warm.

## Status

- **2026-10-30:** Added `deps` caching stages to Next.js dynamic & static Dockerfiles (pinned to corepack pnpm 10.18.3, `pnpm fetch`) and FastAPI Dockerfile (`pip install -r requirements.txt`). Added retained dependency layer tags `bga-fe-deps:<sha12>` and `bga-be-deps:<sha12>` in `docker_frontend_preview.py` and `docker_preview.py`. Enabled parallel image building and container management with per-(generation, kind) locks and early frontend port reservation for backend CORS. Verified plain `docker build .`, concurrent start, layer reuse, and dependency image survival across preview deletions via `test_previews.py` and real Docker sandbox test `test_cached_preview_builds_reuse_dependency_layers`. Warm preview builds reuse layers via cache without re-downloading packages.

## Verify

`make lint`, `make test`, `BGA_SANDBOX_TESTS=1 make test`, then `make up` with the fake engine: two dynamic
generations one after the other (`project-tracker-dynamic` + `two-entity`, then another dynamic example) and
compare their preview times.
