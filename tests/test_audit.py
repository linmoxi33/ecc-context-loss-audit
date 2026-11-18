import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import ck_context_audit as audit  # noqa: E402

CLI = os.path.join(ROOT, "ck_context_audit.py")
IN = os.path.join(ROOT, "examples", "in")


def run(*args):
    p = subprocess.run([sys.executable, CLI] + list(args), capture_output=True, text=True)
    return p


def audit_json(path, *extra):
    p = run(path, "--json", *extra)
    return p, json.loads(p.stdout)


CLEAN_MD = """## What This Is
Demo.

## Next Steps
- one
- two

## Decisions Made
| Decision | Why | Date |
|---|---|---|
| A | because | 2026-01-01 |
"""


class CleanFixture(unittest.TestCase):
    def test_clean_exit_zero(self):
        p = run(os.path.join(IN, "lf-clean"))
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_clean_has_no_errors(self):
        _, d = audit_json(os.path.join(IN, "lf-clean"))
        self.assertEqual(d["summary"]["errors"], 0)
        self.assertEqual(d["mode"], "migrate")

    def test_clean_preserves_content(self):
        _, d = audit_json(os.path.join(IN, "lf-clean"))
        self.assertEqual(d["predicted"]["content_lines"],
                         d["predicted"]["content_lines_preserved"])


class NumberedLists(unittest.TestCase):
    def test_numbered_items_detected(self):
        p, d = audit_json(os.path.join(IN, "lf-numbered"))
        self.assertEqual(p.returncode, 1)
        lines = [f["line"] for f in d["findings"] if f["code"] == "NUMBERED_STEP_DROPPED"]
        self.assertEqual(lines, [19, 20, 21, 27])

    def test_single_digit_space_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "CONTEXT.md"), "w") as fh:
                fh.write("## Next Steps\n1 step kept\n- bullet kept\n2. dropped\n")
            _, d = audit_json(tmp)
            dropped = [f for f in d["findings"] if f["code"] == "NUMBERED_STEP_DROPPED"]
            self.assertEqual([f["line"] for f in dropped], [4])
            self.assertEqual(d["predicted"]["next_steps"], ["step kept", "bullet kept"])

    def test_predicted_file_drops_numbered_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "pred.md")
            p = run(os.path.join(IN, "lf-numbered"), "--write-predicted", out)
            self.assertEqual(p.returncode, 1)
            with open(out) as fh:
                text = fh.read()
            self.assertNotIn("Run the suite.", text.split("## Next Steps")[1][:200])
            self.assertIn("_Not yet recorded._", text)


class Crlf(unittest.TestCase):
    def test_crlf_wipes_all_sections(self):
        p, d = audit_json(os.path.join(IN, "crlf-context"))
        self.assertEqual(p.returncode, 1)
        f = [x for x in d["findings"] if x["code"] == "CRLF_SECTION_WIPE"][0]
        self.assertEqual(len(f["sections_at_risk"]), 8)
        self.assertGreater(f["crlf_bytes"], 0)
        self.assertFalse(any(d["predicted"]["sections"].values()))


class ContextJson(unittest.TestCase):
    def test_unreadable_context_json_is_overwrite_error(self):
        p, d = audit_json(os.path.join(IN, "stale-context-json"))
        self.assertEqual(p.returncode, 1)
        self.assertIn("CONTEXT_JSON_OVERWRITE", [f["code"] for f in d["findings"]])

    def test_already_v2_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "CONTEXT.md"), "w") as fh:
                fh.write(CLEAN_MD)
            with open(os.path.join(tmp, "context.json"), "w") as fh:
                json.dump({"version": 2, "name": "x"}, fh)
            p, d = audit_json(tmp)
            self.assertEqual(p.returncode, 0)
            self.assertEqual(d["mode"], "skipped")
            self.assertEqual(d["summary"]["errors"], 0)


class MemoryFrontmatter(unittest.TestCase):
    def test_colon_space_detected(self):
        p, d = audit_json(os.path.join(IN, "lf-clean"),
                          "--memory-dir", os.path.join(IN, "memory-dir"))
        bad = [f for f in d["findings"] if f["code"] == "MEMORY_FRONTMATTER_INVALID"]
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["file"], "ck_2026-11-18.md")
        self.assertEqual(bad[0]["line"], 2)

    def test_quoted_value_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "ck_ok.md"), "w") as fh:
                fh.write('---\nname: "a: b"\n---\n')
            self.assertEqual(audit.audit_memory_dir(tmp), [])


class Contract(unittest.TestCase):
    def test_json_contract_keys(self):
        _, d = audit_json(os.path.join(IN, "lf-clean"))
        for key in ("tool", "version", "upstream", "mode", "input_sha256",
                    "predicted", "findings", "summary"):
            self.assertIn(key, d)
        self.assertEqual(d["upstream"]["pinned_commit"],
                         "3f14a103a8694e51c1df9a806217a6d0b5f7a6f7")
        self.assertEqual(len(d["input_sha256"]), 64)

    def test_missing_directory_exit_two(self):
        p = run("/nonexistent/ck/project", "--json")
        self.assertEqual(p.returncode, 2)
        self.assertIn("not found", p.stderr)

    def test_replay_is_deterministic(self):
        _, a = audit_json(os.path.join(IN, "lf-numbered"))
        _, b = audit_json(os.path.join(IN, "lf-numbered"))
        self.assertEqual(a["predicted"]["predicted_markdown_sha256"],
                         b["predicted"]["predicted_markdown_sha256"])
        self.assertEqual(a["input_sha256"], b["input_sha256"])


if __name__ == "__main__":
    unittest.main()