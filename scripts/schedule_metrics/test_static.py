"""Offline regression fixtures for Desktop's measure-format metadata rule."""
import unittest
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from validate_static import conflicting_measure_formats, validate_measure_formats, validate_guide_policy


class ReviewPolicyTests(unittest.TestCase):
    def setUp(self):
        self.guide = json.loads((Path(__file__).parent / "metric_guide.json").read_text(encoding="utf-8-sig"))

    def test_authored_policy_matches_eight_check_contract(self):
        self.assertEqual(validate_guide_policy(self.guide), 8)

    def test_rejects_removed_unscored_guide_row(self):
        changed = copy.deepcopy(self.guide)
        changed["rows"].append({"id": "date_alignment_count", "scored": False})
        with self.assertRaisesRegex(AssertionError, "18 rows"):
            validate_guide_policy(changed)

    def test_rejects_high_float_reintroduced_to_score(self):
        changed = copy.deepcopy(self.guide)
        next(row for row in changed["rows"] if row["id"] == "high_float")["scored"] = True
        with self.assertRaisesRegex(AssertionError, "exactly eight"):
            validate_guide_policy(changed)

    def test_rejects_percent_scale_or_wrong_boundary(self):
        for wrong in (0.01, 0.0001, 0.1):
            changed = copy.deepcopy(self.guide)
            next(row for row in changed["rows"] if row["id"] == "invalid_dates")["review_bands"]["amber_max"] = wrong
            with self.assertRaisesRegex(AssertionError, "invalid_dates"):
                validate_guide_policy(changed)

    def test_rejects_binary_aggregation_or_partial_severity_override(self):
        for key, value in (("aggregation", "passed/assessed"), ("coverage", "override_severity")):
            changed = copy.deepcopy(self.guide)
            changed["score_policy"][key] = value
            with self.assertRaisesRegex(AssertionError, "aggregation/severity/coverage"):
                validate_guide_policy(changed)


class MeasureFormatTests(unittest.TestCase):
    def test_rejects_pre_fix_dynamic_measure(self):
        before = (
            "table 'Schedule Metric Detail'\n"
            "\tmeasure 'SM Detail Value' =\n"
            "\t\t\t[SM Baseline Coverage %]\n"
            "\t\tformatString: 0.0%\n"
            "\t\tlineageTag: preserved\n"
            "\t\tformatStringDefinition = [SM Detail Format]\n"
        )
        self.assertEqual(conflicting_measure_formats(before), ["SM Detail Value"])
        after = before.replace("\t\tformatString: 0.0%\n", "")
        self.assertEqual(conflicting_measure_formats(after), [])
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "fixture.tmdl"
            path.write_text(before, encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "SM Detail Value"):
                validate_measure_formats([path])
            path.write_text(after, encoding="utf-8")
            self.assertEqual(validate_measure_formats([path]), 1)

    def test_property_order_and_multiple_measures(self):
        text = (
            "table Test\n"
            "\tmeasure Dynamic = 1\n"
            "\t\tformatStringDefinition = \"0.0%\"\n"
            "\tmeasure Static = 1\n"
            "\t\tformatString: 0.0%\n"
            "\tmeasure 'Invalid ''quoted'' name' = 1\n"
            "\t\tformatStringDefinition = \"0.0%\"\n"
            "\t\tformatString: 0.0%\n"
            "\tcolumn Example\n"
            "\t\tformatString: 0\n"
        )
        self.assertEqual(conflicting_measure_formats(text), ["Invalid 'quoted' name"])

    def test_ignores_expression_text_and_accepts_space_indentation(self):
        text = (
            "table Test\n"
            "    measure Dynamic =\n"
            "            formatString: expression text\n"
            "        formatStringDefinition = \"0.0%\"\n"
        )
        self.assertEqual(conflicting_measure_formats(text), [])


if __name__ == "__main__":
    unittest.main()
