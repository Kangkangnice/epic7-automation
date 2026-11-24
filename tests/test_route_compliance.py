import contextlib
import io
import json
import unittest
from dataclasses import replace
from unittest import mock

from auto_game_unified.games.epic7 import modes
from auto_game_unified.games.epic7.route_contract import RouteContract
from auto_game_unified.tools import route_compliance as compliance


class RouteComplianceTests(unittest.TestCase):
    def test_one_row_per_registered_route(self):
        rows = compliance.build_rows()
        self.assertEqual(len(modes.MODE_SPECS), len(rows))
        self.assertEqual(
            {f"`{name}`" for name in modes.MODE_SPECS},
            {f"`{row['路线'].split('`')[1]}`" for row in rows},
        )

    def test_debt_rows_carry_the_unified_reason(self):
        for row in compliance.build_rows():
            if row["结论"] == "欠债":
                self.assertEqual(modes._CONTRACT_BACKLOG_REASON, row["欠债理由"])
                self.assertEqual("—", row["终点"])

    def test_bad_declaration_is_reported_as_inconsistency(self):
        fake = "fake_route_for_compliance_test"
        bad = RouteContract(
            mode=fake,
            terminal="NO_SUCH_STATE",
            finish_at_home=True,
            overlays=frozenset({"not_a_popup"}),
            empty_states=(),
            action_evidence="transition_contract",
        )
        spec = replace(modes.MODE_SPECS["arena"], name=fake, contract=bad)
        with mock.patch.dict(modes.MODE_SPECS, {fake: spec}):
            row = next(
                row for row in compliance.build_rows() if fake in row["路线"]
            )
        self.assertEqual("不一致", row["结论"])
        self.assertIn("NO_SUCH_STATE", row["终点"])
        self.assertEqual("1 类", row["覆盖层"])

    def test_strict_return_code_follows_declarations(self):
        rows = compliance.build_rows()
        expected = 1 if any(row["结论"] != "达标" for row in rows) else 0
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = compliance.main(["--strict"])
        self.assertEqual(expected, code)
        self.assertIn("路线", out.getvalue())

    def test_json_is_parseable(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = compliance.main(["--json"])
        self.assertEqual(0, code)
        rows = json.loads(out.getvalue())
        self.assertEqual(len(modes.MODE_SPECS), len(rows))
        self.assertIn("结论", rows[0])


if __name__ == "__main__":
    unittest.main()
