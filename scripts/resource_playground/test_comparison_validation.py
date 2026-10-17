"""Focused regressions for the validation repair and independent fixture oracle."""
import datetime as dt
from fractions import Fraction
import unittest

from verify_integration import validate_native_clear_identity, validate_dax_variables, validate_qualified_dax_references
from test_comparison_cases import daily_oracle


class NativeClearIdentity(unittest.TestCase):
    def setUp(self):
        self.expression = {"Column": {"Expression": {"SourceRef": {"Entity": "Scenario Calendar"}}, "Property": "Calendar"}}
        self.entry = {"name": "captured-calendar", "expression": self.expression}

    def test_desktop_omitted_optional_container_is_valid(self):
        validate_native_clear_identity({}, self.entry, self.expression)
        validate_native_clear_identity({"filterConfig": {"filters": []}}, self.entry, self.expression)

    def test_retained_identity_must_match(self):
        validate_native_clear_identity({"filterConfig": {"filters": [{"name": "captured-calendar", "field": self.expression}]}}, self.entry, self.expression)
        with self.assertRaises(AssertionError):
            validate_native_clear_identity({"filterConfig": {"filters": [{"name": "different-calendar", "field": self.expression}]}}, self.entry, self.expression)

    def test_retained_real_filter_on_different_field_is_rejected(self):
        other = {"Column": {"Expression": {"SourceRef": {"Entity": "Scenario Calendar"}}, "Property": "Calendar Name"}}
        with self.assertRaises(AssertionError):
            validate_native_clear_identity({"filterConfig": {"filters": [{"name": "captured-calendar", "field": other, "filter": {"Where": ["selected"]}}]}}, self.entry, self.expression)

    def test_engine_rejected_ordinal_is_guarded_without_rejecting_fix(self):
        for name in ["Ordinal", "ORDINAL", "ordinal"]:
            with self.assertRaises(AssertionError):
                validate_dax_variables([("calendar label", f"VAR {name} = 1 RETURN {name}")], {})
        self.assertEqual(validate_dax_variables([("calendar label", "VAR CalendarOrdinal = 1 RETURN CalendarOrdinal")], {}), 1)

    def test_return_virtual_column_is_not_a_table_reference(self):
        self.assertEqual(validate_qualified_dax_references([("calendar label", "RETURN [__ResolvedLabel]")], {}), 0)
        with self.assertRaises(AssertionError):
            validate_qualified_dax_references([("calendar label", "RETURN MissingTable[Column]")], {})


class IndependentComparisonOracle(unittest.TestCase):
    def setUp(self):
        self.start = dt.date(2026, 10, 19)
        self.spec = {"week": [8, 2, 0, 0, 0, 0, 0], "exceptions": {}, "defect": None}

    def test_cap_applies_before_daily_sum(self):
        result = daily_oracle(self.spec, self.start, self.start + dt.timedelta(days=1), self.start + dt.timedelta(days=1), quantity=1000, rate=10, cap=60, basis="Per working hour")
        self.assertEqual([r[1] for r in result["rows"]], [60, 20])
        self.assertEqual(result["targetRemaining"], 920)

    def test_inverse_preserves_fractional_units(self):
        spec = dict(self.spec, week=[8] * 7)
        result = daily_oracle(spec, self.start, self.start + dt.timedelta(days=17), self.start + dt.timedelta(days=30), quantity=1050, mode="Meet target date", cap=None)
        self.assertEqual(result["required"], Fraction(175, 3))
        self.assertEqual(result["finish"], self.start + dt.timedelta(days=17))
        self.assertEqual(result["targetRemaining"], 0)

    def test_known_completion_survives_later_unknown(self):
        spec = dict(self.spec, exceptions={(self.start + dt.timedelta(days=2)).isoformat(): None})
        done = daily_oracle(spec, self.start, self.start + dt.timedelta(days=10), self.start + dt.timedelta(days=30), quantity=100)
        unknown = daily_oracle(spec, self.start, self.start + dt.timedelta(days=10), self.start + dt.timedelta(days=30), quantity=1000)
        self.assertEqual(done["targetRemaining"], 0)
        self.assertIsNone(unknown["targetRemaining"])
        self.assertEqual(sum(r[1] for r in unknown["rows"]), 200)


if __name__ == "__main__":
    unittest.main()
