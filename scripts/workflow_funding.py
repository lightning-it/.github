"""A synchronization event validates code but does not finalize paid review."""
from __future__ import annotations

from workflow_control import require


def finalized(api, repo, pull, run, event):
    require(pull.get("draft") is False and event.get("pull_request", {}).get("head", {}).get("sha")
            == pull["head"]["sha"], "funding-current-nondraft-head-required")
    if event.get("action") in {"opened", "reopened"}:
        return True
    require(event.get("action") == "synchronize" and type(run.get("created_at")) is str,
            "funding-finalization-event-required")
    # A ready transition after this native head's synchronization explicitly
    # finalizes that unchanged head. A later push has a later native run and
    # therefore cannot consume an older ready transition. Equal-second ordering
    # is deliberately unknown and blocks funding. The authenticated receiver
    # reruns the original classification; it never issues a provider request.
    events = api.pages(f"repos/{repo}/issues/{pull['number']}/events")
    ready = [e for e in events if e.get("event") == "ready_for_review"
             and e.get("actor", {}).get("type") in {"User", "Bot"}
             and type(e.get("created_at")) is str and e["created_at"] > run["created_at"]]
    return bool(ready)
