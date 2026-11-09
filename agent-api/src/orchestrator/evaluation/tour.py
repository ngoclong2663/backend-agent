"""Story 28.6: the evaluation's walker plays the guided tour of each role on the mock API and reports every step as
completed, skipped or stuck. Information only (Epic 26 D4): it never changes the generation and never runs against
the live API (the browser forces the mocks through the kit's `bga-mock-api` switch, so no real record is created).

`tour_plan` is pure (tested without a browser): which demo user plays which tour, and the kind each step has for
that role, as the kit decides it (`effectiveKind`). `play_tours` drives `walk.mjs`'s `tour` command per role and
merges what the browser saw with the plan, so a step the browser never reached is reported too.
"""

from typing import Any

MAX_STEPS = 60


def _effective_kind(step: dict[str, Any], role: str | None) -> str:
    if role and step.get("role") and step["role"] != role:
        return "note"
    if step.get("kind"):
        return str(step["kind"])
    if step.get("automatic") or step.get("skip") or not step.get("target"):
        return "note"
    return "do" if (step.get("target") or {}).get("action") else "look"


def tour_roles(app: dict[str, Any]) -> list[dict[str, Any]]:
    """One demo user per role (the sign-in page's list); an app without sign-in plays as nobody."""
    auth = app.get("auth") or {}
    users = auth.get("demoUsers") or []
    out: list[dict[str, Any]] = []
    for user in users:
        if not any(entry["role"] == user.get("role") for entry in out):
            out.append({"role": user.get("role"), "login": user.get("login")})
    return out or [{"role": None, "login": None}]


def tour_plan(app: dict[str, Any]) -> list[dict[str, Any]]:
    """Per role, the tours it plays and each step's kind for it; empty for an app without workflows."""
    workflows = app.get("workflows") or {}
    tours = workflows.get("tours") or []
    if not tours:
        return []
    plan = []
    for who in tour_roles(app):
        role = who["role"]
        mine = [tour for tour in tours if not role or not tour.get("roles") or role in tour["roles"]]
        plan.append(
            {
                **who,
                "tours": [
                    {
                        "id": tour["id"],
                        "name": tour.get("name"),
                        "steps": [
                            {
                                "id": step["id"],
                                "title": step.get("title"),
                                "role": step.get("role"),
                                "kind": _effective_kind(step, role),
                            }
                            for step in tour.get("steps") or []
                        ],
                    }
                    for tour in mine
                ],
            }
        )
    return plan


def merge_play(planned: dict[str, Any], played: dict[str, Any] | None) -> dict[str, Any]:
    """The browser's results on the planned steps: a step it never reached is `not reached`; its own reason stays."""
    by_id = {(entry.get("tour"), entry.get("id")): entry for entry in (played or {}).get("steps") or []}
    tours = []
    for tour in planned["tours"]:
        steps = []
        for step in tour["steps"]:
            seen = by_id.get((tour["id"], step["id"]))
            steps.append(
                {
                    **step,
                    "result": seen.get("result", "stuck") if seen else "not reached",
                    **({"reason": seen["reason"]} if seen and seen.get("reason") else {}),
                    **({"ms": seen["ms"]} if seen and seen.get("ms") is not None else {}),
                    **({"file": seen["file"]} if seen and seen.get("file") else {}),
                }
            )
        tours.append(
            {
                **tour,
                "steps": steps,
                "completed": bool(played and played.get("completed") and (played.get("tour") in (None, tour["id"]))),
            }
        )
    out = {"role": planned["role"], "login": planned["login"], "tours": tours}
    if played and played.get("error"):
        out["error"] = played["error"]
    if played and played.get("log"):
        out["log"] = played["log"][-40:]
    return out


def play_tours(
    walker: Any, frontend: str, app: dict[str, Any], auth: dict[str, Any] | None, log=None
) -> list[dict[str, Any]]:
    """Plays each role's tour in the browser (`walk.mjs` `tour`) on the mocks and returns the merged results."""
    plan = tour_plan(app)
    if not plan:
        return []
    out = []
    for index, who in enumerate(plan):
        command: dict[str, Any] = {
            "cmd": "tour",
            "url": frontend,
            "role": who["role"],
            "maxSteps": MAX_STEPS,
            "shot": f"/out/tour-{index + 1:02d}-{(who['role'] or 'everyone').replace(':', '-')}",
        }
        if auth and who["login"]:
            command |= {
                "signIn": auth.get("signIn") or "/login",
                "field": auth.get("field", "email"),
                "login": who["login"],
                "password": auth.get("password") or "demo12345",
            }
        try:
            played = walker.send(command)
        except Exception as exc:  # the play is information: a browser that stopped ends it, not the evaluation
            played = {"ok": False, "error": str(exc)[:300], "steps": []}
        for step in played.get("steps") or []:
            if step.get("file"):
                step["file"] = "shots/" + str(step["file"]).rsplit("/", 1)[-1]
        merged = merge_play(who, played)
        if log is not None:
            done = sum(1 for tour in merged["tours"] for step in tour["steps"] if step["result"] == "completed")
            total = sum(len(tour["steps"]) for tour in merged["tours"])
            log(f"  tour as {who['login'] or 'everyone'}: {done}/{total} steps completed")
        out.append(merged)
    return out
