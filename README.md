# ck-context-loss-audit

Predict **before you run it** what affaan-m/ECC's `ck migrate` will delete from your
hand-written `CONTEXT.md` — with the exact source line numbers, offline and read-only.
Why now: ECC ships a migration that overwrites `CONTEXT.md` in place and has no
backup for it, while its own parser silently drops ordinary Markdown numbered lists.

Upstream: https://github.com/affaan-m/ECC

## What upstream does, and what it lacks

`ck` (Context Keeper) is ECC's per-project session memory. Its v1→v2 migration,
[`skills/ck/commands/migrate.mjs`](https://github.com/affaan-m/ECC/blob/3f14a103a8694e51c1df9a806217a6d0b5f7a6f7/skills/ck/commands/migrate.mjs),
parses the user's `CONTEXT.md` with two narrow regexes and then calls
`saveContext()`, which rewrites that file from the parsed model:

- `extractSection()` at [L26-30](https://github.com/affaan-m/ECC/blob/3f14a103a8694e51c1df9a806217a6d0b5f7a6f7/skills/ck/commands/migrate.mjs#L26-L30)
  matches `## Heading\n`; on a CRLF file every section parses as empty and is
  written back as a placeholder.
- `parseBullets()` at [L32-37](https://github.com/affaan-m/ECC/blob/3f14a103a8694e51c1df9a806217a6d0b5f7a6f7/skills/ck/commands/migrate.mjs#L32-L37)
  filters on `^[-*\d]\s`, so standard `1. item` and `10. item` are rejected.
- Only `meta.json` gets a `.v1-backup`
  ([L178-181](https://github.com/affaan-m/ECC/blob/3f14a103a8694e51c1df9a806217a6d0b5f7a6f7/skills/ck/commands/migrate.mjs#L178-L181));
  `CONTEXT.md` is overwritten with no rollback copy.
- An unreadable or non-v2 `context.json` falls through to migration
  ([L97-107](https://github.com/affaan-m/ECC/blob/3f14a103a8694e51c1df9a806217a6d0b5f7a6f7/skills/ck/commands/migrate.mjs#L97-L107))
  and is overwritten, although the file's comment claims the migration "never deletes data".

Open reports with exact reproductions (0 reactions at the time of writing, so this
tool treats them as supporting evidence, not proof):
[#3983 numbered items / CRLF / context.json](https://github.com/affaan-m/ECC/issues/3983),
[#4017 invalid memory frontmatter](https://github.com/affaan-m/ECC/issues/4017).

## What this tool does / does not do

It ports the four parsing rules from the pinned commit above to Python, runs them on
your local project directory, renders the predicted v2 `CONTEXT.md`, and reports every
content line that does not survive — with the original line number. Findings:

| code | severity | meaning |
|---|---|---|
| `CRLF_SECTION_WIPE` | error | CRLF file: all 8 headings parse empty and get replaced |
| `NUMBERED_STEP_DROPPED` | error | `1. item` / `10. item` rejected by `parseBullets` |
| `CONTENT_LINE_LOST` | error | any other content line absent from the predicted output |
| `CONTEXT_JSON_OVERWRITE` | error | existing `context.json` unreadable or v2-less: it will be replaced |
| `MEMORY_FRONTMATTER_INVALID` | error | unquoted `: ` in `memory/ck_*.md` YAML `name:` |
| `DECISION_DATE_REWRITTEN` | warning | renderer replaces per-decision dates with the session date |
| `CONTEXT_MD_NO_BACKUP` | warning | no `CONTEXT.md.v1-backup` exists, migration has no rollback |

It does **not** run `ck`, does not write to your project (unless you pass
`--write-predicted`), does not re-implement `save`/`resume`, and does not predict
`context.json` schema validity beyond the checks listed above.

## Install / usage

Python 3.8+, standard library only, no network.

```bash
python3 ck_context_audit.py examples/in/lf-clean
python3 ck_context_audit.py examples/in/lf-numbered --json
python3 ck_context_audit.py /path/to/.claude/ck/contexts/<project> \
  --memory-dir /path/to/.claude/ck/memory --write-predicted /tmp/predicted-CONTEXT.md
```

First command on the bundled clean fixture prints `content lines: 12, preserved in
prediction: 12, lost: 0` and exits 0. The numbered fixture exits 1 and lists four
dropped items at lines 19, 20, 21 and 27.

`--json` output (abridged):

```json
{
  "tool": "ck-context-loss-audit",
  "upstream": {"repo": "affaan-m/ECC", "pinned_commit": "3f14a10…",
               "file": "skills/ck/commands/migrate.mjs"},
  "mode": "migrate",
  "input_sha256": "…",
  "predicted": {"sections": {"Next Steps": true, "…": true},
                "next_steps": [], "content_lines": 13,
                "content_lines_preserved": 8,
                "predicted_markdown_sha256": "…"},
  "findings": [{"code": "NUMBERED_STEP_DROPPED", "severity": "error", "line": 19,
                "section": "Next Steps", "text": "1. Run the suite."}],
  "summary": {"errors": 4, "warnings": 2, "infos": 1}
}
```

Exit codes: `0` nothing will be lost (warnings allowed), `1` at least one error-level
finding, `2` usage error or unreadable input.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

14 tests, including CLI exit-code behaviour, numbered-list acceptance/rejection,
CRLF section wipe, already-v2 skip, invalid `context.json`, YAML frontmatter quoting,
JSON contract, and replay determinism.

## 与同类项目的差异

`gh search repos "context migration audit"` and `"CONTEXT.md migrate"` returned no
repositories; `"context keeper"` returned projects with ≤156 stars and none audited
migration losses. This tool is not a generic Markdown diff: it re-implements the
upstream parser and renderer at a pinned commit and reports *predicted* loss before
the command runs.

## 本轮创新

First offline **loss predictor** for a destructive agent-memory migration: instead of
diffing before/after files, it ports the migration's own parser and renderer (pinned
commit) and produces a byte-accounted forecast of what `ck migrate` will destroy,
including the CRLF whole-file wipe and the `1. item` numbered-list bug documented in
upstream's own issue #3983. No existing tool in the ledger or on GitHub does this.

## Limitations

- The port is tied to commit `3f14a103…`; if upstream fixes the regexes, this tool's
  predictions become stale (the commit is printed in every report).
- `renderContextMd` layout is ported, but session ids and fallback dates are
  placeholders when `meta.json` lacks them; only content preservation is asserted.
- The generic `CONTENT_LINE_LOST` check is textual (bullet prefix and whitespace
  normalized); it does not understand semantic rewording.
- Memory frontmatter checking covers `memory/ck_*.md` only, and only the `name:` key.
- Fixtures are reconstructions of the v1 `CONTEXT.md` format implied by the parser;
  upstream ships no v1 sample, so no real user context file is bundled.

## License

MIT. Not affiliated with affaan-m/ECC; upstream code was read, not vendored.
