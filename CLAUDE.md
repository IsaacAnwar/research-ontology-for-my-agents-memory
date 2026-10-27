# kg

Experiment provenance and hypothesis graph stored as notes in an Obsidian vault. `src/kg/vault.py` holds all logic. `cli.py` and `server.py` are thin wrappers over `Vault`.

## Architecture

Two layers in one folder of the vault:

- `runs/` is provenance. One note per experiment run, written only by `kg log-run` from JSON the experiment code emits. Append-only. Agents never edit these notes by hand.
- `claims/` and `questions/` are hypotheses. Agents write them through `propose`. A claim's `status` is computed by `kg check` from its links and is never written by hand.

Generated files: `kg.base` (Obsidian Bases views) and `_synthesis.md` (rebuilt on every check).

Edges are frontmatter lists of wikilinks, so they show in Obsidian's graph view:

| edge | from | to |
| --- | --- | --- |
| `supports` | claim | run |
| `contradicts` | claim | run |
| `depends_on` | claim | claim |
| `related` | claim or question | anything |

Status rules, applied in order, counting only runs with `valid` not false:

| status | rule |
| --- | --- |
| refuted | more contradicting runs than supporting |
| contested | at least one contradicting run |
| established | at least 2 supporting runs and `approved_by` set by the human |
| supported | at least 2 supporting runs |
| preliminary | 1 supporting run |
| untested | no runs |
| blocked | would be supported or established, but a `depends_on` claim is not |

Approval never overrides evidence. An established claim falls back when its runs are invalidated or contradicted.

## Setup

When the user asks to set up kg:

1. Install: `uv tool install --reinstall .` in this repo. This puts `kg` and `kg-mcp` on PATH. Rerun it after every code change. Avoid editable installs: macOS can set the hidden flag on `.pth` files, and Python skips hidden `.pth` files.
2. Ask the user where the graph should live. Default to a folder inside their existing Obsidian vault, for example `<vault>/experiments`. Do not create a new `.obsidian` folder.
3. Scaffold it: `kg init <path>`.
4. Register the MCP server at user scope:
   `claude mcp add kg -s user -e KG_VAULT=<absolute path> -- kg-mcp`
5. Tell the user to export `KG_VAULT=<absolute path>` in their shell profile so the CLI finds the vault, and to open `kg.base` in Obsidian for the Claims, Runs, and Questions tables.

## Logging runs

Experiment code, local or on GCP, writes one JSON object per run. No dependency on this package is needed where the experiment runs:

```json
{
  "id": "vertex-run-name-or-omit",
  "git_sha": "output of git rev-parse HEAD",
  "git_dirty": false,
  "data_version": "dataset-v2",
  "source": "https://console.cloud.google.com/vertex-ai/experiments/...",
  "config": {"model": "resnet18", "lr": 0.001, "epochs": 3},
  "metrics": {"val_acc": 0.812},
  "artifacts": ["gs://bucket/runs/0041/"],
  "notes": "free text, becomes the note body"
}
```

`git_sha` must come from the machine that ran the code. Any extra keys are kept as properties. Without `id`, runs are numbered `run-0001`, `run-0002`, and so on.

Ingest locally:

```
kg log-run run.json
gcloud storage cat gs://bucket/runs/*.json | kg log-run
```

A file may hold one object or a list. Already-logged ids are skipped.

## Agent routine

Agents reach the graph through six MCP tools: `search`, `why`, `impact`, `propose`, `invalidate`, `check`. The CLI has the same commands plus `init` and `log-run` (`kg propose` reads its arguments as JSON on stdin). The routine is in the server instructions in `src/kg/server.py`. Keep it in sync with this file:

1. Write candidate ideas before reading the graph.
2. `search` each idea for duplicates and prior runs. A refuted or contested claim only rules out its stated conditions.
3. `why` a claim before relying on it.
4. `propose` a question for an untested idea, or a claim once runs exist.
5. `invalidate` a run when a bug is found in it.
6. `check` at the end of a session.

## Code style

No comments. Keep the tool count small; add a `Vault` method before adding a tool.
