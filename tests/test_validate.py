import unittest
from datetime import datetime, timezone
from decimal import Decimal

from hl7bridge.validate import errors, validate_bundle

PATIENT = {"resourceType": "Patient", "id": "p1", "identifier": [{"system": "urn:x", "value": "1"}]}
GOOD_OBS = {"resourceType": "Observation", "id": "o1", "status": "final", "code": {"text": "Sodium"},
            "subject": {"reference": "Patient/p1"}, "valueQuantity": {"value": Decimal("140"), "unit": "mmol/L"}}


def bundle(*resources, patient=True):
    entries = []
    if patient:
        entries.append({"fullUrl": "urn:uuid:p1x", "resource": PATIENT, "request": {"method": "POST", "url": "Patient"}})
    for r in resources:
        entries.append({"resource": r, "request": {"method": "PUT", "url": f"{r['resourceType']}/{r['id']}"}})
    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}


class StructuralTests(unittest.TestCase):
    def test_valid_bundle_has_no_errors(self):
        self.assertEqual(errors(validate_bundle(bundle(GOOD_OBS))), [])

    def test_not_a_bundle(self):
        self.assertTrue(errors(validate_bundle({"resourceType": "Observation"})))

    def test_empty_bundle(self):
        self.assertTrue(errors(validate_bundle({"resourceType": "Bundle", "type": "transaction", "entry": []})))

    def test_entry_without_request_method(self):
        b = {"resourceType": "Bundle", "type": "transaction", "entry": [{"resource": GOOD_OBS, "request": {"url": "Observation/o1"}}]}
        self.assertTrue(errors(validate_bundle(b)))

    def test_put_url_must_match_resource(self):
        b = bundle(GOOD_OBS)
        b["entry"][-1]["request"]["url"] = "Observation/different-id"
        self.assertTrue(errors(validate_bundle(b)))

    def test_duplicate_resource_id_detected(self):
        b = bundle(GOOD_OBS)
        b["entry"].append({"resource": GOOD_OBS, "request": {"method": "PUT", "url": "Observation/o1"}})
        self.assertTrue(errors(validate_bundle(b)))

    def test_dangling_reference_detected(self):
        orphan = dict(GOOD_OBS, id="o2", subject={"reference": "Patient/does-not-exist"})
        self.assertTrue(errors(validate_bundle(bundle(orphan))))

    def test_reference_to_sibling_in_bundle_is_fine(self):
        dr = {"resourceType": "DiagnosticReport", "id": "d1", "status": "final", "code": {"text": "x"},
              "subject": {"reference": "Patient/p1"}, "result": [{"reference": "Observation/o1"}]}
        self.assertEqual(errors(validate_bundle(bundle(GOOD_OBS, dr))), [])


class ModelAndBindingTests(unittest.TestCase):
    def test_bad_status_code_caught(self):
        bad = dict(GOOD_OBS, status="not-a-real-status")
        self.assertTrue(errors(validate_bundle(bundle(bad))))

    def test_missing_required_field_caught(self):
        bad = {k: v for k, v in GOOD_OBS.items() if k != "status"}
        self.assertTrue(errors(validate_bundle(bundle(bad))))

    def test_unknown_resource_type_is_an_error_not_a_crash(self):
        bad = {"resourceType": "NotARealResource", "id": "x1"}
        issues = validate_bundle(bundle(bad))
        self.assertTrue(errors(issues))


class SemanticRuleTests(unittest.TestCase):
    def test_observation_needs_value_or_absent_reason(self):
        bad = {k: v for k, v in GOOD_OBS.items() if k != "valueQuantity"}
        self.assertTrue(errors(validate_bundle(bundle(bad))))

    def test_observation_value_and_absent_reason_are_exclusive(self):
        bad = dict(GOOD_OBS, dataAbsentReason={"coding": [{"system": "x", "code": "unknown"}]})
        self.assertTrue(errors(validate_bundle(bundle(bad))))

    def test_data_absent_reason_alone_is_valid(self):
        ok = {k: v for k, v in GOOD_OBS.items() if k != "valueQuantity"}
        ok["dataAbsentReason"] = {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/data-absent-reason", "code": "unknown"}]}
        self.assertEqual(errors(validate_bundle(bundle(ok))), [])

    def test_future_result_time_rejected(self):
        bad = dict(GOOD_OBS, effectiveDateTime="2099-01-01T00:00:00+00:00")
        self.assertTrue(errors(validate_bundle(bundle(bad), now=datetime(2026, 1, 1, tzinfo=timezone.utc))))

    def test_future_birthdate_rejected(self):
        b = bundle(GOOD_OBS)
        b["entry"][0]["resource"] = dict(PATIENT, birthDate="2099-01-01")
        self.assertTrue(errors(validate_bundle(b, now=datetime(2026, 1, 1, tzinfo=timezone.utc))))

    def test_final_report_without_results_or_conclusion_is_a_warning_not_an_error(self):
        dr = {"resourceType": "DiagnosticReport", "id": "d1", "status": "final", "code": {"text": "x"}, "subject": {"reference": "Patient/p1"}}
        issues = validate_bundle(bundle(dr))
        self.assertEqual(errors(issues), [])
        self.assertTrue(any(i.severity == "warning" for i in issues))

    def test_decimal_precision_round_trips_through_validation(self):
        q = dict(GOOD_OBS, valueQuantity={"value": Decimal("1.40"), "unit": "mg/dL"})
        self.assertEqual(errors(validate_bundle(bundle(q))), [])


if __name__ == "__main__":
    unittest.main()
