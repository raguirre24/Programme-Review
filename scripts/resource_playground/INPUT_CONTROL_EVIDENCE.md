# Resource Playground input and page evidence

The page uses native `textSlicer` Input slicers bound to ordinary disconnected columns. A supported typed number filters a row in its input table. A DD-MM-YYYY date filters the matching `Date Input` text row, which determines the same row's `Date`. Inputs remain subject to the documented bounds and increments.

## Implementation evidence

On 11 September 2026, the installed Power BI Desktop `2.157.1354.0` was inspected read-only under its Windows Store installation's `bin/WebView2Resources/minerva/scripts` directory:

- `desktop.min.js`, module `761262`: the registered visual is `textSlicer`; its `Values` grouping role permits text, numeric and integer columns. Its objects include `general.filter`, `general.selectedValues`, `slicerSettings.multiselect`, `slicerSettings.numericInputOnly` and `dropdown.filterMode`.
- `desktop.TextSlicerVisual.min.js`: plain numeric input is converted to a semantic equality comparison. Numeric ranges and comparison operators also exist, so the DAX engine separately rejects selections that do not resolve to exactly one supported value.
- The same implementation's text equality mode is `Filter_Is_Any`. The date controls bind this mode to `dd-MM-yyyy` strings. Native IsAny builds an equality expression with a text constant; it does not parse the entry as a regional date. Thus `03-04-2027` matches 3 April only. Changing a date format string on the underlying Date column alone does not change typed entry; the formatted text projection must also change.
- Native `selectedValues` serialisation uses `kind: "ExprList"` and `exprs` containing expressions. Numeric controls persist both their equality filter and their displayed text so opening or resetting the report restores the same input.
- Native legacy cards use the `wordWrap.show` property. This is distinct from unsupported `labels.wordWrap`.

This inspection establishes implementation and capability only. Separate live Desktop input results are recorded below; Service feature-switch parity has not been established.

## Page contract

- New page: `4c53a34bba9dcc7f3e8c`, immediately after Resources, 1920 × 1080.
- 12 isolated scenario input slicers plus three shared context slicers: visible Project and Monthly update, with hidden State matching the existing report. Their sync groups are Project, last_recalc_date and State respectively. They remain outside Reset.
- The Reset example is 1,050 × 1 m³, production 120 per working date, daily limit 100. Calendar is deliberately unselected. The user's saved scenario can differ. Clearing an input uses the model's stated defaults, reflected in the evaluated-input summary.
- Native field-parameter binding switches the chart between Week and Month without restoring scenario values. Month is the default; Day is not a chart option.
- The chart, daily table and calculations can use today through the end of the shared date axis, inclusive, with no fixed twelve-month cap. The daily table includes the final permitted date instead of imposing a fixed 365-row limit.
- Chart and table clicks cannot filter scenario inputs, result cards or each other.
- Reset bookmark `e899bf3a9c2d243f33bf` is scoped to these 12 inputs with both `targetVisualNames` and `options.applyOnlyToTargetVisuals=true`, and suppresses display and active-page changes. Native replay clears calendar/date selections. The calendar uses single selection with `strictSingleSelect=false` so an empty selection is allowed.
- Existing native navigators use automatic page inclusion. Their home-only variants retain their existing home-only policy; no existing page visuals need modification.

## Open-horizon native verification

After Desktop applied the revised model, **Optimize → Refresh visuals** was needed to replace cached one-year text with the new date-coverage text. This refreshed visual queries; no source-data refresh was performed. The introduction, evaluated inputs and chart title then consistently displayed coverage through 31-12-2036.

Typing start `13-09-2028` and pressing Enter produced first work 13-09-2028, finish 01-02-2029, 100 working dates and 142 elapsed dates. Typing target `31-12-2030` and pressing Enter produced quantity by target 5,000 and remaining zero, with the same finish. Both Week and Month charts rendered the future forecast without errors.

The latest user inputs had both Start and Target cleared before this change. Clearing both test dates restored evaluated start 11-09-2026, default target 11-10-2026, finish 02-02-2027, 100 working dates, 145 elapsed dates, target quantity 1,050 and remaining 3,950. Project, August 2026, 4d Tunnel, 5,000 m³, rate 50 and cap 100 were retained. Month was restored and native Save completed at 21:35. Full observations are in `resource_playground_review/open_horizon_20260911/NATIVE_ACCEPTANCE.md`; this verifies the existing Desktop process, not Service or a full process restart.

## Earlier shared-context and rolling-window native verification

These observations record the preceding twelve-month version. The later open-horizon request supersedes its upper-bound rejection rule; historical results are retained here without being presented as current acceptance.

After applying this refinement in the existing Desktop process, the saved 5,000 m³ / rate 50 / cap 100 scenario retained its result: finish 02-02-2027, 100 working dates and 145 elapsed dates. Project and August 2026 were visible, the calendar displayed only 4d Tunnel, and the chart opened in Month view. The introduction displayed the inclusive 11-09-2026 to 11-09-2027 window.

Changing Monthly update to June changed the calendar list and removed August-only calendar names. Returning to August restored that context. Week and Month were the only chart choices, and Week rendered successfully. Typed 13-09-2026 evaluated to that exact start with first work on 14-09-2026. Typed 10-09-2026 and 12-09-2027 each produced an explicit permitted-window message with blank result cards, chart and daily rows.

Native Reset through the bound bookmark cleared the calendar and dates and restored the sample's Month/rate 120 values while retaining the selected Project and August 2026. Complete observations are recorded in the separate refinement review artifact `NATIVE_ACCEPTANCE.md`. Only one project currently has live calendar rows; cross-project and restricted-role isolation are separate executed-fixture tests.

## Earlier repair verification

The observations below precede the shared-context and rolling-window refinement. Revised feature checks are recorded separately; the earlier Day/365-date evidence is retained for provenance.

Structural checks passed for JSON parsing, unique IDs, canvas bounds, scenario-only bindings, absence of sync groups, interaction references and reset scope. The cached Microsoft Power BI authoring CLI `0.1.4` reported no new page, bookmark or visual-capability diagnostics relative to repository HEAD after correction of card wrapping and title height.

After the final repair was applied in Desktop, native checks confirmed:

- Chart and six-field daily-table rendering in forward and inverse modes without the earlier visual errors.
- Day, Week and Month switching, plus Focus Mode.
- Typing hourly rate `12.3` produced evaluated daily capacity `98.4` on an eight-hour working date.
- Typing unsupported rate `12.35` produced the explicit invalid-input message; no rounded selection was substituted.
- Hourly inverse calculation with a daily cap remained explicitly unsupported.
- Reset from a selected calendar, Day view and rate 1,050 cleared calendar/date selections and restored Month, rate 120, quantity 1,050 and daily cap 100. Results became blank and the status requested one authorised calendar version.
- Reset preserved both original global filters as False. `report.json` remained byte-identical after saving, confirming that the repaired bookmark did not change those existing report settings.

These observations are separate from the executed-DAX fixture's 101 passing logical cases and 2,512 assertions across all 47 measures. The final 60 expressions matched source in both the processed fixture and the applied production model. Production metadata reported all 99 playground partitions, columns and measures Ready without errors. See [VALIDATION.md](VALIDATION.md) for the full separation of static, engine and native-host evidence.

The Reset repair addressed two native behaviours: strict calendar selection prevented clearing, and target names without `options.applyOnlyToTargetVisuals=true` did not limit bookmark replay to those visuals.

The final saved-source reload check passed using **Apply external changes** after restoring the original 12 inputs. Returning to Resource Playground retained the selected August calendar, Day view, quantity 1,050, rate 1,050 and cap 100. The chart and all six daily columns rendered, reporting finish 25 September 2026, 11 working days, 15 civil days and a partial final allocation of 50. The report was saved again. This was verified within the existing Desktop process, not after a full process restart.

Further Desktop and Service acceptance should cover remaining empty/range/date-input combinations, reset after changing every input, unavailable numeric Input slicer features, wrapping and calendar-name legibility at other display scales, keyboard interaction, accessible labels, export and production permission roles. Test evaluated values rather than relying only on the text displayed in an input. No Service publication or Service input acceptance is claimed.

Generate a review draft with `python scripts/resource_playground/generate_page.py --output-dir <draft-folder>` from the repository. The script refuses to overwrite the deployed page. Compare the draft with the current page and apply targeted changes that preserve Desktop's saved metadata, visual IDs and user selections.
