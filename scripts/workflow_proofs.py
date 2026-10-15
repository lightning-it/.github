"""Keep native acceptance references small; full release packaging is separate."""
from __future__ import annotations

import json

import single_review_resources as resources


def read_native_json(path, maximum):
    contract = resources.memory_contract()
    limit = min(maximum, contract["max_wire_bytes"])
    if not path.is_file() or path.is_symlink() or not 0 < path.stat().st_size <= limit:
        raise ValueError("native-proof-resource-admission")
    # Admission precedes reading or decoding. Account for decoded nodes and
    # simultaneous Unicode/serialization copies using the existing contract.
    payload = path.read_bytes()
    if len(payload) > limit:
        raise ValueError("native-proof-resource-admission")
    resources.preflight_json(payload, contract["max_json_nodes"], contract["max_json_depth"])
    return json.loads(payload)


class References:
    """One shared resource reservation for compact references, never full proofs."""
    def __init__(self, maximum):
        contract = resources.memory_contract()
        self.remaining = min(maximum, contract["max_wire_bytes"]) - 2
        self.nodes = contract["max_json_nodes"] - 1
        self.items = []

    def append(self, value):
        wire = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        resources.preflight_json(wire, self.nodes, resources.MAX_JSON_DEPTH)
        pending = [value]
        nodes = 0
        while pending:
            item = pending.pop()
            nodes += 1
            if isinstance(item, dict):
                nodes += len(item)
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
        cost = len(wire) + 1
        if cost > self.remaining or nodes > self.nodes:
            raise ValueError("native-reference-aggregate-resource-admission")
        self.remaining -= cost
        self.nodes -= nodes
        self.items.append(value)
