#!/usr/bin/env python3
"""Offline, bounded contract audit. Python 3.12 standard library only."""
import argparse
import json
import math
import sys
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024
MAX_ITEMS = 10000
class BadInput(ValueError):
    pass
class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise BadInput("invalid command arguments")

def require(condition, message):
    if not condition:
        raise BadInput(message)

def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate JSON object key")
        result[key] = value
    return result

def reject_constant(value):
    raise BadInput("nonfinite JSON number")

def read_text(path):
    require(Path(path).is_file(), "input must be a regular file")
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    require(len(raw) <= MAX_BYTES, "input exceeds 2 MiB limit")
    return raw.decode("utf-8-sig")

def finite_float(value):
    parsed = float(value)
    require(math.isfinite(parsed), "nonfinite JSON number")
    return parsed

def load_json(path):
    return json.loads(read_text(path), object_pairs_hook=pairs, parse_constant=reject_constant, parse_float=finite_float)

def report(findings, **summary):
    return {"schema_version": 1, "tool": TOOL, "status": "findings" if findings else "pass", "summary": summary, "findings": findings}

def finding(code, **where):
    return {"code": code, **where}

def run(build_parser, action):
    try:
        parser = Parser(description=__doc__)
        build_parser(parser)
        result = action(parser.parse_args())
        status = 1 if result["status"] == "findings" else 0
    except (ValueError, OSError, UnicodeError, RecursionError, OverflowError) as exc:
        message = str(exc) if isinstance(exc, BadInput) else "unreadable or malformed input"
        result = {"schema_version": 1, "tool": TOOL, "status": "error", "error": message}
        status = 2
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, allow_nan=False))
    return status

TOOL = "dependency-cycle-audit"

def audit(data):
    require(isinstance(data, dict) and set(data) == {"nodes", "edges"}, "expected nodes and edges")
    nodes, edges = data["nodes"], data["edges"]
    require(isinstance(nodes, list) and len(nodes) <= MAX_ITEMS, "nodes must be a bounded array")
    require(all(isinstance(n, str) and 0 < len(n) <= 256 for n in nodes), "node IDs must be nonempty strings")
    require(len(nodes) == len(set(nodes)), "duplicate node ID")
    require(isinstance(edges, list) and len(edges) <= 50000, "edges must be a bounded array")
    indices = {name: i for i, name in enumerate(nodes)}
    adj, reverse = [[] for _ in nodes], [[] for _ in nodes]
    findings, seen, selfloops = [], set(), set()
    for i, edge in enumerate(edges):
        require(isinstance(edge, list) and len(edge) == 2 and all(isinstance(n, str) for n in edge), "each edge must be two node IDs")
        if edge[0] not in indices or edge[1] not in indices:
            findings.append(finding("missing_node", edge_index=i))
            continue
        a, b = indices[edge[0]], indices[edge[1]]
        if (a, b) in seen:
            findings.append(finding("duplicate_edge", edge_index=i))
            continue
        seen.add((a, b)); adj[a].append(b); reverse[b].append(a)
        if a == b:
            selfloops.add(a)
            findings.append(finding("self_loop", node_index=a))
    # Iterative Kosaraju avoids recursion limits even for a long acyclic chain.
    visited, order = set(), []
    for node in range(len(nodes)):
        if node in visited:
            continue
        visited.add(node); stack = [(node, 0)]
        while stack:
            current, cursor = stack[-1]
            if cursor == len(adj[current]):
                order.append(current); stack.pop(); continue
            child = adj[current][cursor]; stack[-1] = (current, cursor + 1)
            if child not in visited:
                visited.add(child); stack.append((child, 0))
    visited, components = set(), []
    for node in reversed(order):
        if node in visited:
            continue
        component, stack = [], [node]; visited.add(node)
        while stack:
            current = stack.pop(); component.append(current)
            for child in reverse[current]:
                if child not in visited:
                    visited.add(child); stack.append(child)
        components.append(sorted(component))
    cyclic = sorted((c for c in components if len(c) > 1), key=lambda c: c[0])
    for component in cyclic:
        findings.append(finding("dependency_cycle", node_indices=component))
    return report(findings, nodes=len(nodes), edges=len(edges), strongly_connected_components=len(components), cyclic_components=sum(len(c) > 1 or c[0] in selfloops for c in components))

def configure(parser):
    parser.add_argument("input", help="local graph JSON")
if __name__ == "__main__":
    sys.exit(run(configure, lambda args: audit(load_json(args.input))))
