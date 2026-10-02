"""Closed read routes for LI-228; shared LI-227 bounded I/O, no mutable operation."""

import importlib.util
import json
import os
from pathlib import Path
import re
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("shadow_transport_kernel",
                                            ROOT / "scripts/required-review-transport.py")
TRANSPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRANSPORT)
require = TRANSPORT.require
THREAD_QUERY = """query($owner:String!,$name:String!,$number:Int!){
repository(owner:$owner,name:$name){pullRequest(number:$number){
number headRefOid baseRefOid lastEditedAt
reviews(first:100){totalCount pageInfo{hasNextPage}
nodes{id body lastEditedAt commit{oid}}}
reviewThreads(first:100){totalCount pageInfo{hasNextPage}
nodes{id isResolved comments(first:100){totalCount pageInfo{hasNextPage}
nodes{id body updatedAt author{login}}}}}}}}"""


PREFIX = "repos/lightning-it/.github"
ID = r"[1-9][0-9]{0,18}"
SHA = r"[0-9a-f]{40}"
PAGE = r"per_page=100&page=[1-3]"
ROUTES = tuple(re.compile(re.escape(PREFIX) + "/" + pattern) for pattern in (
    rf"actions/runs/{ID}", rf"pulls/{ID}", rf"check-runs/{ID}",
    r"branches/develop", r"rules/branches/develop",
    rf"compare/{SHA}\.\.\.{SHA}",
    rf"commits/{SHA}/check-runs\?filter=all&{PAGE}",
    rf"actions/runs/{ID}/jobs\?filter=all&{PAGE}",
    rf"pulls/{ID}/reviews\?{PAGE}",
    rf"pulls/{ID}/reviews/{ID}/comments\?{PAGE}",
    rf"issues/{ID}/comments\?{PAGE}",
    rf"commits/{SHA}/pulls\?{PAGE}",
    rf"pulls\?state=open&base=develop&{PAGE}",
))


class API(TRANSPORT.GitHubReader):
    def __init__(self, policy):
        require(type(policy.get("max_pages")) is int and 1 <= policy["max_pages"] <= 3,
                "invalid-page-budget")
        self.policy = policy
        super().__init__(max_seconds=policy["max_seconds"], max_requests=policy["max_requests"])

    def read(self, endpoint, variables=None):
        require(type(endpoint) is str, "unsupported-resource")
        if endpoint == "graphql":
            require(type(variables) is dict and set(variables) == {"owner", "name", "number"}
                    and variables["owner"] == "lightning-it" and variables["name"] == ".github"
                    and type(variables["number"]) is int
                    and 1 <= variables["number"] <= 2 ** 63 - 1, "thread-scope")
            body = json.dumps({"query": THREAD_QUERY, "variables": variables}).encode()
        else:
            require(variables is None and any(route.fullmatch(endpoint) for route in ROUTES),
                    "unsupported-resource")
            body = None
        token = os.environ.get("GH_TOKEN", "")
        require(bool(token.strip()), "token-missing")
        request = urllib.request.Request(TRANSPORT.ORIGIN + "/" + endpoint, data=body,
            method="POST" if body is not None else "GET",
            headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                     "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28"})
        return self._read_json(request)

    def inventory(self, path, field=None):
        records = []
        expected_total = None
        for page in range(1, self.policy["max_pages"] + 1):
            payload = self.read(path + ("&" if "?" in path else "?")
                                + f"per_page=100&page={page}")
            items = payload if field is None else payload.get(field)
            require(type(items) is list and len(items) <= 100, "inventory-shape")
            if field is not None:
                total = payload.get("total_count")
                require(type(total) is int and total >= 0, "inventory-total")
                require(expected_total is None or total == expected_total,
                        "inventory-total-drift")
                expected_total = total
            records.extend(items)
            require(all(type(item) is dict and type(item.get("id")) is int and item["id"] > 0
                        for item in records), "inventory-id")
            require(len({item["id"] for item in records}) == len(records),
                    "inventory-duplicate")
            if len(items) < 100:
                require(expected_total is None or expected_total == len(records),
                        "inventory-incomplete")
                return records
        raise TRANSPORT.ReadFailure("inventory-page-limit")
