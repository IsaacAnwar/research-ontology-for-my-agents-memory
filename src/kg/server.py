import os
from functools import wraps

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from kg.vault import Vault

INSTRUCTIONS = """Experiment knowledge graph. Runs are raw provenance written by experiment code. Claims are hypotheses whose status kg computes from linked runs. Questions are untested ideas.

Routine:
1. Write your own candidate ideas before reading the graph.
2. search each idea to find duplicates and prior runs. A refuted or contested claim only rules out its stated conditions.
3. why a claim before relying on it, and read the runs at the bottom of the chain.
4. propose a question for an idea, or a claim once runs exist. Cite run ids in supports and contradicts. Never restate a claim with new conditions; propose a new one.
5. invalidate a run when you find a bug in it, then read the impact.
6. check at the end of a session and report problems and status changes.

You never write runs, status, or approved_by."""

mcp = MCPServer("kg", instructions=INSTRUCTIONS)
vault = Vault(os.environ.get("KG_VAULT", "."))


def tool(fn):
    @wraps(fn)
    def call(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ValueError, FileNotFoundError, FileExistsError) as e:
            raise ToolError(str(e)) from e

    return mcp.tool()(call)


@tool
def search(text: str, kind: str | None = None, limit: int = 10) -> list[dict]:
    """Find runs, claims, or questions whose id, properties, or body match the words in text. kind filters to run, claim, or question."""
    return vault.search(text, kind, limit)


@tool
def why(id: str) -> dict:
    """Evidence tree for a claim: supporting and contradicting runs and the claims it depends on, down to raw runs."""
    return vault.why(id)


@tool
def impact(id: str) -> list[dict]:
    """Every claim downstream of a run or claim, with current status and the edge that links it."""
    return vault.impact(id)


@tool
def propose(
    kind: str,
    statement: str,
    id: str | None = None,
    conditions: dict | None = None,
    supports: list[str] | None = None,
    contradicts: list[str] | None = None,
    depends_on: list[str] | None = None,
    related: list[str] | None = None,
    note: str = "",
) -> dict:
    """Create a claim or question, or add links and a dated note to an existing one. kind is claim or question. statement and conditions are fixed once written. supports and contradicts take run ids, depends_on takes claim ids, related takes any ids. Returns the computed status."""
    return vault.propose(kind, statement, id, conditions, supports, contradicts, depends_on, related, note)


@tool
def invalidate(id: str, reason: str) -> dict:
    """Mark a run invalid, for example after finding a bug or data leak. Returns affected claims and status changes."""
    return vault.invalidate(id, reason)


@tool
def check() -> dict:
    """Recompute every claim status, rewrite _synthesis.md, and report broken links, missing provenance, and status changes."""
    return vault.check()


def main():
    mcp.run()
