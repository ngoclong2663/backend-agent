"""The plugins' frontends (Story 22.7) on the workshop-bookings example (auth, roles, rules, uploads, payments, links):
the screens the planner adds, the files the scaffold copies, `app.json`, the mock API's plugin data, and both token
modes (decision P8). Agent tests, no Node (decision FE-TESTS); the sandbox build and the scenarios run in
`tests/sandbox/test_frontend_sandbox.py`."""

import json
import re
import sys
from pathlib import Path

import pytest

from src.modules.shared.domain.frontend_spec import validate_frontend_spec_data
from src.orchestrator.checks.consistency import check_spec_pair
from src.orchestrator.frontend.planner import plan_frontend

sys.path.insert(0, str(Path(__file__).parent))
from test_app_screens import _example, _plan  # noqa: E402

TEMPLATES = Path(__file__).parents[1] / "templates"
KIT = TEMPLATES / "nextjs_overlay/files/dynamic/app/src/components/app"
DYNAMIC = TEMPLATES / "nextjs_overlay/files/dynamic"
PLUGINS = TEMPLATES / "plugins"


@pytest.fixture(scope="module")
def workshop(tmp_path_factory):
    from src.orchestrator.frontend.scaffold import scaffold_frontend

    backend, raw = _example("workshop-bookings")
    backend, _, contract, screens = _plan(backend, raw)
    spec = validate_frontend_spec_data(screens.spec).normalized
    out = tmp_path_factory.mktemp("workshop")
    plan = plan_frontend(spec, contract)
    scaffold_frontend(out, plan, spec, contract)
    return backend, contract, spec, plan, out


def _json(out: Path, relative: str):
    return json.loads((out / relative).read_text())


def test_the_screens_of_every_plugin_and_a_clean_pair_check(workshop):
    backend, _, spec, _, _ = workshop
    routes = {page["route"]: page for page in spec["pages"]}
    assert {"/login", "/register", "/payments/success", "/payments/cancel"} <= set(routes)
    assert routes["/login"]["sections"][0]["component"] == "AppAuth" and spec["auth"]["signIn"] == "login"
    detail = routes["/bookings/[id]"]["sections"][0]["content"]["actions"]
    moves = {action["id"]: action for action in detail}
    assert moves["transition-confirmed"]["body"] == {"status": "CONFIRMED"}
    assert moves["transition-confirmed"]["allow"] == "transition:CONFIRMED"
    assert "confirm" in moves["transition-cancelled"], "a move into a locked state asks first"
    assert moves["pay"]["kind"] == "pay" and moves["pay"]["allow"] == "pay"
    links = next(s for s in routes["/workshops/[id]"]["sections"] if s["component"] == "AppLinks")
    assert (links["data"]["operationId"], links["data"]["params"]) == ("workshop.listTags", {"id": "$route.id"})
    assert links["content"]["add"]["field"] == "tagId" and links["content"]["remove"]["param"] == "tagId"
    assert links["content"]["add"]["reference"]["listOperation"] == "tag.list"
    assert not check_spec_pair(spec, backend)


def test_forms_upload_files_move_states_and_leave_server_fields_out(workshop):
    _, _, spec, _, _ = workshop
    forms = {form["id"]: {f["name"]: f for f in form["fields"]} for form in spec["forms"]}
    cover = forms["workshop_create"]["cover"]
    assert (
        cover["upload"]
        == {
            "entity": "Workshop",
            "field": "cover",
            "presign": "files.presign",
            "kind": "image",
            "accept": cover["upload"]["accept"],
            "maxSize": 5242880,
        }
        and "image/png" in cover["upload"]["accept"]
    )
    created = forms["booking_create_in_workshop"]
    assert "status" not in created, "a new booking starts PENDING; it moves by its transitions"
    assert "paymentStatus" not in created and "ownerId" not in created, "the server's and the signed-in user's"
    assert forms["booking_update"]["status"]["transition"] is True
    assert "paymentStatus" not in forms["booking_update"]
    assert set(forms["auth_login"]) == {"email", "password"} and forms["auth_login"]["password"]["type"] == "password"


def test_the_scaffold_copies_each_plugins_frontend_and_names_it(workshop):
    _, _, _, plan, out = workshop
    assert plan["app"]["plugins"] == ["auth-jwt", "storage", "payments", "relations"]
    for relative in (
        "src/components/plugins/auth-jwt/AppAuth.tsx",
        "src/components/plugins/auth-jwt/session.ts",
        "src/app/api/auth/login/route.ts",
        "src/app/api/backend/[...path]/route.ts",
        "src/proxy.ts",
        "src/lib/auth/server.ts",
        "src/components/plugins/storage/UploadField.tsx",
        "src/components/plugins/payments/PayAction.tsx",
        "src/components/plugins/relations/AppLinks.tsx",
        "src/app/login/page.tsx",
        "src/app/payments/success/page.tsx",
    ):
        assert (out / relative).is_file(), relative
    registry = (out / "src/components/app/plugins.ts").read_text()
    assert 'export { AppAuth, UserMenu, useSession, signInDemo } from "@/components/plugins/auth-jwt";' in registry
    assert 'export { AppLinks } from "@/components/plugins/relations";' in registry
    assert {"progress", "badge", "card", "dropdown-menu", "command", "popover"} <= set(plan["shadcn"])


def test_an_app_without_plugins_gets_the_stubs(tmp_path):
    from src.orchestrator.frontend.scaffold import scaffold_frontend

    backend, raw = _example("flashcards")
    _, _, contract, screens = _plan(backend, raw)
    spec = validate_frontend_spec_data(screens.spec).normalized
    plan = plan_frontend(spec, contract)
    scaffold_frontend(tmp_path, plan, spec, contract)
    assert plan["app"]["plugins"] == [] and not (tmp_path / "src/components/plugins").exists()
    assert not (tmp_path / "src/proxy.ts").exists() and not (tmp_path / "src/app/api/backend").exists()
    registry = (tmp_path / "src/components/app/plugins.ts").read_text()
    assert registry.count('from "./plugin-stubs";') == 4
    data = _json(tmp_path, "src/content/app.json")
    assert data["auth"] is None and data["access"] == {}


def test_app_json_says_who_may_do_what(workshop):
    _, _, _, _, out = workshop
    data = _json(out, "src/content/app.json")
    assert data["auth"]["signIn"] == "/login" and data["auth"]["loginField"] == "email"
    assert {user["role"] for user in data["auth"]["demoUsers"]} == {"member", "organizer"}
    assert data["access"]["workshop.create"] == {"secured": True, "roles": ["organizer"]}
    assert data["access"]["booking.list"] == {"secured": True}
    assert "workshop.list" not in data["access"], "workshops are public"
    assert data["entities"]["Workshop"]["fields"]["cover"] == {"type": "image", "urlField": "coverUrl"}


def test_the_mock_api_acts_as_the_plugins(workshop):
    _, _, _, _, out = workshop
    plugins = _json(out, "src/mocks/plugins.json")
    assert plugins["auth"]["roles"][0] == "member", "a new account takes the first role, as the backend's sign-up"
    assert {user["login"] for user in plugins["auth"]["demoUsers"]} >= {"demo-member@example.com"}
    assert {rule["code"] for rule in plugins["rules"]} == {"INVALID_TRANSITION", "RESOURCE_LOCKED", "CAPACITY_REACHED"}
    assert plugins["storage"]["fields"]["Workshop.cover"]["maxSize"] == 5242880
    assert plugins["payments"]["amountField"] == "amount" and plugins["payments"]["paid"] == "PAID"
    assert plugins["links"]["workshop.addTag"]["parentField"] == "workshopId"
    assert _json(out, "src/mocks/defaults.json")["Booking"]["status"] == "PENDING"
    operations = {op["operationId"]: op for op in _json(out, "src/mocks/operations.json")}
    assert operations["booking.get"]["secured"] and operations["booking.get"]["policy"]["type"] == "ownership"
    assert operations["tag.create"]["policy"] == {"name": "organizersOnly", "type": "role", "roles": ["organizer"]}
    scenarios = _json(out, "src/mocks/scenarios.json")
    assert scenarios["notEmulated"] == {"FILE_NOT_FOUND": 1, "webhooks": 1}
    assert scenarios["login"]["path"] == "/auth/login"
    named = {(s["operationId"], s["name"]): s for s in scenarios["scenarios"]}
    assert any(s.get("user") for s in scenarios["scenarios"]), "a scenario run as another demo user"
    for (op, name), scenario in named.items():  # signed in, except the scenario that checks the refusal without
        if op.startswith("booking."):
            assert bool(scenario.get("auth")) == (name != "no token"), (op, name)
    handlers = (DYNAMIC / "src/mocks/plugins.ts").read_text()
    for check in (
        "export function gate(",
        "export function scope(",
        "export function actionsFor(",
        "export function ruleRefusal(",
    ):
        assert check in handlers, check
    # Story 25.1 (F6): separately unique fields are each unique on their own, as the backend's indexes are
    assert "for (const field of conflict.fields as string[])" in handlers
    assert "fields.every((field) => String(row[field])" not in handlers.split("uniqueTogether")[-1]


@pytest.mark.parametrize("mode", ["local", "cookie"])
def test_both_token_modes(mode):
    """Decision P8: `local` keeps the token in the browser and sends a bearer header; `cookie` keeps it in an httpOnly
    cookie the Next server sets, calls go through its same-origin proxy, and pages are guarded on the server. A 401
    signs the user out and asks them to sign in again, either way."""
    client = (DYNAMIC / "src/lib/api/client.ts").read_text()
    route = (DYNAMIC / "src/app/api/runtime-config/route.ts").read_text()
    assert 'authTokenStorage: process.env.AUTH_TOKEN_STORAGE === "cookie" ? "cookie" : "local"' in route
    session = (PLUGINS / "auth-jwt/frontend/files/src/components/plugins/auth-jwt/session.ts").read_text()
    server = (PLUGINS / "auth-jwt/frontend/files/src/lib/auth/server.ts").read_text()
    if mode == "local":
        assert "if (token) headers.authorization = `Bearer ${token}`;" in client
        assert "storeToken(token.accessToken);" in session
        page = (KIT / "AppPage.tsx").read_text()
        assert "router.replace(`${app.auth.signIn}?next=" in page, "guarded in the browser"
    else:
        assert 'if (config.authTokenStorage === "cookie") return { base: "/api/backend", token: null };' in client
        assert 'serverAuth("/api/auth/login", values)' in session
        assert "httpOnly: true" in server and 'sameSite: "lax"' in server
        proxy = (PLUGINS / "auth-jwt/frontend/files/src/app/api/backend/[...path]/route.ts").read_text()
        assert "if (!sameOrigin(request))" in proxy and 'headers.set("authorization", `Bearer ${token}`)' in proxy
        guard = (PLUGINS / "auth-jwt/frontend/files/src/proxy.ts").read_text()
        assert "export function proxy(request: NextRequest)" in guard and "NextResponse.redirect(target)" in guard
    assert 'if (response.status === 401 && (token || base === "/api/backend")) unauthorized?.();' in client
    menu = (PLUGINS / "auth-jwt/frontend/files/src/components/plugins/auth-jwt/UserMenu.tsx").read_text()
    assert "onUnauthorized(() => {" in menu and "?next=" in menu


def test_only_the_token_helper_touches_local_storage():
    """The `conventions` check flags a token in localStorage; the app's only use is the `local` mode helper
    (`src/lib/auth/token.ts`, generator-owned, so the check does not scan it)."""
    from src.orchestrator.checks.frontend_conventions import OWNED_PREFIXES

    users = []
    for root in (DYNAMIC, *(p / "frontend/files" for p in PLUGINS.iterdir())):
        for path in root.rglob("*.ts*"):
            if "localStorage." in path.read_text():
                users.append(path.relative_to(root).as_posix())
    # Story 26.4 / 28.5: the guided tour keeps its progress per user (`bga-tour…` keys, never a token); Story 28.6:
    # the runtime config reads the evaluation browser's mock switch; Story 30.3: the mock API reads the design plugin
    # check's state switch (`bga-mock-state`)
    assert sorted(users) == [
        "app/src/components/app/tour/progress.test.ts",
        "app/src/components/app/tour/progress.ts",
        "src/lib/auth/token.ts",
        "src/lib/runtime-config.ts",
        "src/mocks/handlers.ts",
    ]
    assert "src/lib/auth/token.ts".startswith(OWNED_PREFIXES)
    for name in ("AppTour.tsx", "progress.ts"):
        assert "token" not in (DYNAMIC / "app/src/components/app/tour" / name).read_text().lower()


def test_the_preview_passes_the_token_mode():
    source = (Path(__file__).parents[1] / "src/preview/docker_frontend_preview.py").read_text()
    assert '"AUTH_TOKEN_STORAGE": config.preview_auth_token_storage' in source
    readme = (DYNAMIC / "README.md").read_text()
    assert "Use `cookie` in production." in readme
    assert re.search(r"^AUTH_TOKEN_STORAGE=local$", (DYNAMIC / ".env.example").read_text(), re.MULTILINE)
