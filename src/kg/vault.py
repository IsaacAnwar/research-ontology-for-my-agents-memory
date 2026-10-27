import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

FOLDERS = {"run": "runs", "claim": "claims", "question": "questions"}
EDGES = {"supports": "run", "contradicts": "run", "depends_on": "claim", "related": None}
EVIDENCE = ("supports", "contradicts", "depends_on")
RESERVED = {"type", "valid", "invalid_reason", "invalidated", "logged", "id", "notes"}
MIN_SUPPORT = 2
HOLDING = {"supported", "established"}
ORDER = ["established", "supported", "blocked", "contested", "preliminary", "untested", "refuted"]
BRIEF = {
    "run": ("valid", "invalid_reason", "git_sha", "data_version", "config", "metrics"),
    "claim": ("status", "statement", "conditions"),
    "question": ("statement",),
}
FRONT = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.S)
LINK = re.compile(r"^\[\[([^\]|#]+)[^\]]*\]\]$")
BASE = """views:
  - type: table
    name: Claims
    filters:
      and:
        - 'type == "claim"'
    order:
      - note.status
      - file.name
      - note.statement
      - note.conditions
    groupBy:
      property: note.status
      direction: ASC
  - type: table
    name: Runs
    filters:
      and:
        - 'type == "run"'
    order:
      - file.name
      - note.valid
      - note.data_version
      - note.git_sha
      - note.metrics
  - type: table
    name: Questions
    filters:
      and:
        - 'type == "question"'
    order:
      - file.name
      - note.statement
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:80]


def link(node_id):
    return f"[[{node_id}]]"


def unlink(value):
    value = str(value).strip()
    match = LINK.match(value)
    return match.group(1).strip() if match else value


def read_note(path):
    text = path.read_text()
    match = FRONT.match(text)
    if not match:
        return {}, text
    return yaml.safe_load(match.group(1)) or {}, match.group(2).lstrip("\n")


def write_note(path, meta, body=""):
    text = "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n"
    body = body.strip()
    path.write_text(text + (f"\n{body}\n" if body else ""))


def edges(node, name):
    return [unlink(v) for v in node["meta"].get(name) or []]


def valid_runs(node, name, nodes):
    return sum(1 for r in edges(node, name) if r in nodes and nodes[r]["kind"] == "run" and nodes[r]["meta"].get("valid", True) is not False)


def brief(node):
    meta = node["meta"]
    return {"id": node["id"], "kind": node["kind"], **{k: meta[k] for k in BRIEF[node["kind"]] if k in meta}}


class Vault:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()

    def init(self):
        for folder in FOLDERS.values():
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        base = self.root / "kg.base"
        if not base.exists():
            base.write_text(BASE)
        self.check()
        return str(self.root)

    def load(self):
        nodes, dupes = {}, []
        for kind, folder in FOLDERS.items():
            for path in sorted((self.root / folder).glob("*.md")):
                meta, body = read_note(path)
                if path.stem in nodes:
                    dupes.append(path.stem)
                nodes[path.stem] = {"id": path.stem, "kind": kind, "path": path, "meta": meta, "body": body}
        return nodes, dupes

    def log_run(self, record):
        record = dict(record)
        runs = self.root / FOLDERS["run"]
        run_id = slugify(record["id"]) if record.get("id") else self._next_run_id()
        path = runs / f"{run_id}.md"
        if path.exists():
            raise FileExistsError(f"{run_id} already logged; runs are append-only")
        meta = {"type": "run", "valid": True, "logged": now()}
        meta.update({k: v for k, v in record.items() if k not in RESERVED and v is not None})
        write_note(path, meta, record.get("notes") or "")
        return run_id

    def _next_run_id(self):
        numbers = [int(m.group(1)) for p in (self.root / FOLDERS["run"]).glob("run-*.md") if (m := re.fullmatch(r"run-(\d+)", p.stem))]
        return f"run-{max(numbers, default=0) + 1:04d}"

    def propose(self, kind, statement, id=None, conditions=None, supports=(), contradicts=(), depends_on=(), related=(), note=""):
        if kind not in ("claim", "question"):
            raise ValueError("kind must be claim or question")
        if kind == "question" and (supports or contradicts or depends_on or conditions):
            raise ValueError("questions only take related links; propose a claim to record evidence")
        node_id = slugify(id or statement)
        path = self.root / FOLDERS[kind] / f"{node_id}.md"
        meta, body = read_note(path) if path.exists() else ({"type": kind, "statement": statement}, "")
        if meta.get("statement") != statement:
            raise ValueError(f"{node_id} exists with a different statement; propose a new {kind} instead")
        if conditions is not None:
            if meta.get("conditions") not in (None, conditions):
                raise ValueError(f"{node_id} exists with different conditions; propose a new claim instead")
            meta["conditions"] = conditions
        for name, values in (("supports", supports), ("contradicts", contradicts), ("depends_on", depends_on), ("related", related)):
            merged = list(dict.fromkeys(edges({"meta": meta}, name) + [unlink(v) for v in values or ()]))
            if merged:
                meta[name] = [link(v) for v in merged]
        if note:
            body = f"{body.rstrip()}\n\n## {now()[:10]}\n\n{note.strip()}"
        write_note(path, meta, body)
        report = self.check()
        node = self.load()[0][node_id]
        return {**brief(node), "problems": [p for p in report["problems"] if p.startswith(f"{node_id}:")]}

    def invalidate(self, run_id, reason):
        path = self.root / FOLDERS["run"] / f"{unlink(run_id)}.md"
        if not path.exists():
            raise FileNotFoundError(f"no run {run_id}")
        meta, body = read_note(path)
        meta.update(valid=False, invalid_reason=reason, invalidated=now())
        write_note(path, meta, body)
        report = self.check()
        return {"impact": self.impact(run_id), "changes": report["changes"]}

    def check(self):
        nodes, dupes = self.load()
        problems = [f"{d}: duplicate id across folders" for d in dupes]
        for node in nodes.values():
            for name, want in EDGES.items():
                for target in edges(node, name):
                    other = nodes.get(target)
                    if other is None:
                        problems.append(f"{node['id']}: {name} links missing note {target}")
                    elif want and other["kind"] != want:
                        problems.append(f"{node['id']}: {name} links {other['kind']} {target}, expected {want}")
            if node["kind"] == "run" and not node["meta"].get("git_sha"):
                problems.append(f"{node['id']}: run has no git_sha")
            if node["kind"] != "run" and not node["meta"].get("statement"):
                problems.append(f"{node['id']}: missing statement")
        status = {}
        for node in nodes.values():
            if node["kind"] == "claim":
                self._status(node["id"], nodes, status, set(), problems)
        changes = []
        for claim_id, value in status.items():
            node = nodes[claim_id]
            if node["meta"].get("status") != value:
                changes.append({"id": claim_id, "from": node["meta"].get("status"), "to": value})
                node["meta"]["status"] = value
                write_note(node["path"], node["meta"], node["body"])
        self._synthesize(nodes)
        return {"problems": list(dict.fromkeys(problems)), "changes": changes, "counts": dict(Counter(status.values()))}

    def _status(self, claim_id, nodes, memo, stack, problems):
        if claim_id in memo:
            return memo[claim_id]
        if claim_id in stack:
            problems.append(f"{claim_id}: depends_on cycle")
            return "blocked"
        stack.add(claim_id)
        node = nodes[claim_id]
        support, contra = valid_runs(node, "supports", nodes), valid_runs(node, "contradicts", nodes)
        if contra > support:
            value = "refuted"
        elif contra:
            value = "contested"
        elif support >= MIN_SUPPORT:
            value = "established" if node["meta"].get("approved_by") else "supported"
        elif support:
            value = "preliminary"
        else:
            value = "untested"
        deps = [d for d in edges(node, "depends_on") if d in nodes and nodes[d]["kind"] == "claim"]
        if value in HOLDING and any(self._status(d, nodes, memo, stack, problems) not in HOLDING for d in deps):
            value = "blocked"
        stack.discard(claim_id)
        memo[claim_id] = value
        return value

    def _synthesize(self, nodes):
        lines = ["# Synthesis", "", "Generated by `kg check` from runs and claims. Edits here are overwritten.", ""]
        claims = [n for n in nodes.values() if n["kind"] == "claim"]
        for value in ORDER:
            group = [n for n in claims if n["meta"].get("status") == value]
            if not group:
                continue
            lines += [f"## {value.capitalize()}", ""]
            for n in group:
                cond = ", ".join(f"{k}={v}" for k, v in (n["meta"].get("conditions") or {}).items())
                evidence = f"+{valid_runs(n, 'supports', nodes)} / -{valid_runs(n, 'contradicts', nodes)}"
                lines.append(f"- {link(n['id'])} {n['meta'].get('statement', '')} ({cond or 'no conditions'}; {evidence})")
            lines.append("")
        questions = [n for n in nodes.values() if n["kind"] == "question"]
        if questions:
            lines += ["## Open questions", ""] + [f"- {link(n['id'])} {n['meta'].get('statement', '')}" for n in questions] + [""]
        invalid = [n for n in nodes.values() if n["kind"] == "run" and n["meta"].get("valid") is False]
        if invalid:
            lines += ["## Invalid runs", ""] + [f"- {link(n['id'])} {n['meta'].get('invalid_reason', '')}" for n in invalid] + [""]
        path = self.root / "_synthesis.md"
        text = "\n".join(lines)
        if not path.exists() or path.read_text() != text:
            path.write_text(text)

    def search(self, text, kind=None, limit=10):
        terms = text.lower().split()
        hits = []
        for node in self.load()[0].values():
            if kind and node["kind"] != kind:
                continue
            haystack = " ".join([node["id"], yaml.safe_dump(node["meta"]), node["body"]]).lower()
            score = sum(term in haystack for term in terms)
            if score:
                hits.append((score, node))
        hits.sort(key=lambda h: -h[0])
        return [brief(node) for _, node in hits[:limit]]

    def why(self, node_id):
        return self._tree(unlink(node_id), self.load()[0], frozenset())

    def _tree(self, node_id, nodes, seen):
        node = nodes.get(node_id)
        if node is None:
            return {"id": node_id, "missing": True}
        out = brief(node)
        if node_id in seen:
            return out
        for name in EVIDENCE:
            targets = edges(node, name)
            if targets:
                out[name] = [self._tree(t, nodes, seen | {node_id}) for t in targets]
        return out

    def impact(self, node_id):
        node_id = unlink(node_id)
        nodes = self.load()[0]
        reverse = defaultdict(list)
        for node in nodes.values():
            for name in EVIDENCE:
                for target in edges(node, name):
                    reverse[target].append((node["id"], name))
        out, queue, seen = [], [node_id], {node_id}
        while queue:
            current = queue.pop(0)
            for source, name in reverse[current]:
                if source not in seen:
                    seen.add(source)
                    queue.append(source)
                    out.append({**brief(nodes[source]), "via": f"{name} {current}"})
        return out
