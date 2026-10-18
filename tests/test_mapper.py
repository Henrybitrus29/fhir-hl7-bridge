import unittest
from decimal import Decimal

from hl7bridge import hl7v2 as h
from hl7bridge.mapper import MapConfig, MappingError, UnsupportedMessage, convert
from hl7bridge.validate import errors, validate_bundle
from tests.helpers import OBR, PID, entries, msg, obx, seg


def convert_text(text: str, cfg: MapConfig | None = None):
    return convert(h.parse(text), cfg)


def bundle_of(*segments, **kw):
    return convert_text(msg(PID, OBR, *segments, **kw)).bundle


class DeterminismTests(unittest.TestCase):
    def test_same_message_gives_same_ids(self):
        b1 = bundle_of(obx())
        b2 = bundle_of(obx())
        ids1 = sorted(e["resource"].get("id", e.get("fullUrl")) for e in b1["entry"])
        ids2 = sorted(e["resource"].get("id", e.get("fullUrl")) for e in b2["entry"])
        self.assertEqual(ids1, ids2)

    def test_different_patient_different_id(self):
        b1 = bundle_of(obx())
        other_pid = seg("PID", {1: "1", 3: "MRN999^^^HOSP^MR", 5: "OTHER^PERSON"})
        b2 = convert_text(msg(other_pid, OBR, obx())).bundle
        self.assertNotEqual(entries(b1, "Patient")[0]["identifier"], entries(b2, "Patient")[0]["identifier"])

    def test_patient_create_is_conditional_on_identifier(self):
        e = bundle_of(obx())["entry"][0]
        self.assertEqual(e["request"]["method"], "POST")
        self.assertEqual(e["request"]["url"], "Patient")
        self.assertIn("identifier=", e["request"]["ifNoneExist"])

    def test_clinical_resources_use_put_with_matching_id(self):
        b = bundle_of(obx())
        for rtype in ("DiagnosticReport", "Observation"):
            for r in entries(b, rtype):
                matching = [e for e in b["entry"] if e["resource"] is r]
                self.assertEqual(matching[0]["request"]["url"], f"{rtype}/{r['id']}")


class PatientTests(unittest.TestCase):
    def test_demographics(self):
        p = entries(bundle_of(obx()), "Patient")[0]
        self.assertEqual(p["name"][0]["family"], "TESTPATIENT")
        self.assertEqual(p["name"][0]["given"], ["ALEX"])
        self.assertEqual(p["birthDate"], "1980-02-14")
        self.assertEqual(p["gender"], "male")

    def test_missing_identifier_rejected(self):
        with self.assertRaises(MappingError):
            convert_text(msg(seg("PID", {1: "1", 5: "NOID^PATIENT"}), OBR, obx()))

    def test_multiple_identifiers_mr_preferred_as_key(self):
        pid = seg("PID", {1: "1", 3: "ALT1^^^OTHER^PI~MRN7^^^HOSP^MR", 5: "X^Y"})
        b = convert_text(msg(pid, OBR, obx())).bundle
        ident = entries(b, "Patient")[0]["identifier"]
        self.assertEqual(len(ident), 2)
        conv = convert_text(msg(pid, OBR, obx()))
        self.assertIn("MRN7", conv.bundle["entry"][0]["request"]["ifNoneExist"])

    def test_unknown_assigning_authority_gets_sender_scoped_system_and_warns(self):
        pid = seg("PID", {1: "1", 3: "7788^^^^MR", 5: "X^Y"})
        conv = convert_text(msg(pid, OBR, obx()))
        system = conv.bundle["entry"][0]["resource"]["identifier"][0]["system"]
        self.assertTrue(system.startswith("urn:hl7v2:"), system)
        self.assertTrue(any("no assigning authority" in w for w in conv.warnings))

    def test_system_map_overrides_default(self):
        cfg = MapConfig(system_map={"HOSP": "https://hospital.example/patient-ids"})
        b = convert_text(msg(PID, OBR, obx()), cfg).bundle
        self.assertEqual(entries(b, "Patient")[0]["identifier"][0]["system"], "https://hospital.example/patient-ids")

    def test_iso_oid_authority(self):
        pid = seg("PID", {1: "1", 3: "9^^^HOSP&2.16.840.1.113883.19.5&ISO^MR", 5: "X^Y"})
        b = convert_text(msg(pid, OBR, obx())).bundle
        self.assertEqual(entries(b, "Patient")[0]["identifier"][0]["system"], "urn:oid:2.16.840.1.113883.19.5")

    def test_escaped_name_component(self):
        pid = seg("PID", {1: "1", 3: "M1^^^HOSP^MR", 5: r"O\T\Brien^Pat"})
        b = convert_text(msg(pid, OBR, obx())).bundle
        self.assertEqual(entries(b, "Patient")[0]["name"][0]["family"], "O&Brien")

    def test_unrecognised_gender_is_omitted_not_guessed(self):
        pid = seg("PID", {1: "1", 3: "M1^^^HOSP^MR", 5: "X^Y", 8: "Z"})
        conv = convert_text(msg(pid, OBR, obx()))
        self.assertNotIn("gender", conv.bundle["entry"][0]["resource"])
        self.assertTrue(any("gender" in w for w in conv.warnings))

    def test_partial_birth_date(self):
        pid = seg("PID", {1: "1", 3: "M1^^^HOSP^MR", 5: "X^Y", 7: "1980"})
        b = convert_text(msg(pid, OBR, obx())).bundle
        self.assertEqual(entries(b, "Patient")[0]["birthDate"], "1980")


class ValueTypeTests(unittest.TestCase):
    def test_numeric_with_units_and_decimal_precision_preserved(self):
        b = bundle_of(obx(val="1.40", unit="mg/dL"))
        q = entries(b, "Observation")[0]["valueQuantity"]
        self.assertEqual(q["value"], Decimal("1.40"))
        self.assertEqual(str(q["value"]), "1.40")
        self.assertEqual(q["system"], "http://unitsofmeasure.org")

    def test_numeric_comparator(self):
        b = bundle_of(obx(val="<0.1", unit="mg/dL"))
        self.assertEqual(entries(b, "Observation")[0]["valueQuantity"]["comparator"], "<")

    def test_nm_type_declared_but_not_numeric_falls_back_to_string(self):
        conv = convert_text(msg(PID, OBR, obx(val="trace", unit="")))
        obs = entries(conv.bundle, "Observation")[0]
        self.assertEqual(obs["valueString"], "trace")
        self.assertTrue(any("not numeric" in w for w in conv.warnings))

    def test_sn_simple_comparator(self):
        b = bundle_of(obx(typ="SN", val="<^10", unit="mg/dL"))
        self.assertEqual(entries(b, "Observation")[0]["valueQuantity"],
                        {"value": Decimal("10"), "comparator": "<", "unit": "mg/dL", "system": "http://unitsofmeasure.org", "code": "mg/dL"})

    def test_sn_range(self):
        b = bundle_of(obx(typ="SN", val="^5^-^10", unit="mg/dL"))  # comp1=cmp(empty) comp2=5 comp3=- comp4=10
        rng = entries(b, "Observation")[0]["valueRange"]
        self.assertEqual((rng["low"]["value"], rng["high"]["value"]), (Decimal("5"), Decimal("10")))

    def test_string_types(self):
        for typ in ("ST", "TX", "FT"):
            b = bundle_of(obx(typ=typ, val="free text result"))
            self.assertEqual(entries(b, "Observation")[0]["valueString"], "free text result")

    def test_coded_value(self):
        b = bundle_of(obx(typ="CWE", val="3092008^Staphylococcus aureus^SCT"))
        cc = entries(b, "Observation")[0]["valueCodeableConcept"]
        self.assertEqual(cc["coding"][0], {"system": "http://snomed.info/sct", "code": "3092008", "display": "Staphylococcus aureus"})

    def test_unknown_code_system_mapped_to_placeholder_and_warns(self):
        conv = convert_text(msg(PID, OBR, obx(typ="CWE", val="X1^Something^LOCALCODES")))
        obs = entries(conv.bundle, "Observation")[0]
        self.assertTrue(obs["valueCodeableConcept"]["coding"][0]["system"].startswith("urn:hl7v2:codesystem:"))
        self.assertTrue(any("not a known terminology" in w for w in conv.warnings))

    def test_datetime_value(self):
        b = bundle_of(obx(typ="DTM", val="20260101120000"))
        self.assertEqual(entries(b, "Observation")[0]["valueDateTime"], "2026-01-01T12:00:00+00:00")

    def test_embedded_document_rejected_not_dropped(self):
        with self.assertRaises(MappingError):
            convert_text(msg(PID, OBR, obx(typ="ED", val="PDF^Base64^AAAA")))

    def test_missing_value_sets_data_absent_reason(self):
        b = bundle_of(obx(val=""))
        obs = entries(b, "Observation")[0]
        self.assertEqual(obs["dataAbsentReason"]["coding"][0]["code"], "unknown")
        self.assertNotIn("valueQuantity", obs)

    def test_cancelled_missing_value_reason_is_not_performed(self):
        b = bundle_of(obx(val="", status="X"))
        self.assertEqual(entries(b, "Observation")[0]["dataAbsentReason"]["coding"][0]["code"], "not-performed")


class ReferenceRangeAndInterpretationTests(unittest.TestCase):
    def test_range_parsed(self):
        b = bundle_of(obx(rng="136-145"))
        rr = entries(b, "Observation")[0]["referenceRange"][0]
        self.assertEqual((rr["low"]["value"], rr["high"]["value"]), (Decimal("136"), Decimal("145")))

    def test_less_than_range(self):
        b = bundle_of(obx(rng="<5.0"))
        self.assertEqual(entries(b, "Observation")[0]["referenceRange"][0]["high"]["value"], Decimal("5.0"))

    def test_interpretation_known_code(self):
        b = bundle_of(obx(flag="H"))
        self.assertEqual(entries(b, "Observation")[0]["interpretation"][0]["coding"][0]["code"], "H")


class ReportAndOrderTests(unittest.TestCase):
    def test_order_identifiers_and_status(self):
        b = convert_text(msg(PID, seg("ORC", {1: "RE", 9: "20260101100000"}), OBR, obx())).bundle
        sr = entries(b, "ServiceRequest")[0]

        self.assertEqual({i["value"] for i in sr["identifier"]}, {"P1", "F1"})
        self.assertEqual(sr["authoredOn"], "2026-01-01T10:00:00+00:00")

    def test_report_links_to_order_and_observations(self):
        b = bundle_of(obx(1), obx(2, code="2823-3^Potassium^LN", val="4.0"))
        dr = entries(b, "DiagnosticReport")[0]
        sr = entries(b, "ServiceRequest")[0]
        self.assertEqual(dr["basedOn"][0]["reference"], f"ServiceRequest/{sr['id']}")
        self.assertEqual(len(dr["result"]), 2)

    def test_multiple_obr_blocks_produce_separate_reports(self):
        obr2 = seg("OBR", {1: "2", 2: "P2", 3: "F2", 4: "789-8^Hematology^LN", 25: "F"})
        b = convert_text(msg(PID, OBR, obx(1), obr2, obx(1, code="789-8^RBC^LN", val="4.5"))).bundle
        self.assertEqual(len(entries(b, "DiagnosticReport")), 2)
        self.assertEqual(len(entries(b, "Observation")), 2)

    def test_no_order_numbers_still_produces_report_without_service_request(self):
        obr_bare = seg("OBR", {1: "1", 4: "51990-0^BMP^LN", 25: "F"})
        conv = convert_text(msg(PID, obr_bare, obx()))
        self.assertEqual(entries(conv.bundle, "ServiceRequest"), [])
        self.assertEqual(len(entries(conv.bundle, "DiagnosticReport")), 1)
        self.assertTrue(any("placer or filler" in w for w in conv.warnings))

    def test_obx_before_obr_rejected(self):
        with self.assertRaises(MappingError):
            convert_text(msg(PID, obx()))

    def test_notes_become_report_conclusion(self):
        b = convert_text(msg(PID, OBR, "NTE|1||Called to floor nurse at 09:10.", obx())).bundle
        self.assertIn("Called to floor nurse", entries(b, "DiagnosticReport")[0]["conclusion"])

    def test_notes_after_obx_attach_to_that_observation(self):
        b = bundle_of(obx(), "NTE|1||Hemolyzed specimen.")
        obs = entries(b, "Observation")[0]
        self.assertEqual(obs["note"][0]["text"], "Hemolyzed specimen.")

    def test_result_status_maps_to_fhir_status(self):
        b = convert_text(msg(PID, seg("OBR", {1: "1", 2: "P1", 3: "F1", 4: "x^y^LN", 25: "C"}), obx(status="C"))).bundle
        self.assertEqual(entries(b, "DiagnosticReport")[0]["status"], "corrected")


class MessageLevelTests(unittest.TestCase):
    def test_wrong_message_type_rejected(self):
        with self.assertRaises(UnsupportedMessage):
            convert_text(msg(PID, mtype="ADT^A01^ADT_A01"))

    def test_test_processing_id_rejected_by_default(self):
        with self.assertRaises(MappingError):
            convert_text(msg(PID, OBR, obx(), proc="T"))

    def test_test_processing_id_accepted_when_configured(self):
        conv = convert_text(msg(PID, OBR, obx(), proc="T"), MapConfig(accept_processing_ids=("P", "T")))
        self.assertEqual(conv.counts["Observation"], 1)

    def test_no_pid_rejected(self):
        with self.assertRaises(MappingError):
            convert_text(msg(OBR, obx()))

    def test_duplicate_pid_rejected(self):
        with self.assertRaises(MappingError):
            convert_text(msg(PID, PID, OBR, obx()))

    def test_no_obx_rejected(self):
        with self.assertRaises(MappingError):
            convert_text(msg(PID, OBR))

    def test_unsupported_segment_is_skipped_with_warning(self):
        conv = convert_text(msg(PID, OBR, obx(), "PV1|1|I"))
        self.assertTrue(any("PV1" in w for w in conv.warnings))
        self.assertEqual(conv.counts["Observation"], 1)

    def test_counts(self):
        conv = convert_text(msg(PID, OBR, obx(1), obx(2, code="2823-3^Potassium^LN", val="4")))
        self.assertEqual(conv.counts, {"Patient": 1, "ServiceRequest": 1, "DiagnosticReport": 1, "Observation": 2})

    def test_missing_control_id_warns_but_does_not_reject(self):
        raw = "MSH|^~\\&|A|B|C|D|2026||ORU^R01||P|2.5\r" + PID + "\r" + OBR + "\r" + obx() + "\r"
        conv = convert_text(raw)
        self.assertTrue(any("control id" in w for w in conv.warnings))


class EndToEndValidationTests(unittest.TestCase):
    def test_all_sample_messages_validate_clean(self):
        import os

        from tests.helpers import SAMPLES
        for name in os.listdir(SAMPLES):
            if not name.startswith("oru_"):
                continue
            with self.subTest(name=name):
                with open(os.path.join(SAMPLES, name), "rb") as f:
                    conv = convert(h.parse(f.read()))
                issues = validate_bundle(conv.bundle)
                self.assertEqual(errors(issues), [], f"{name}: {[str(i) for i in errors(issues)]}")

    def test_all_bad_samples_are_rejected_or_fail_validation(self):
        import os

        from tests.helpers import SAMPLES
        for name in os.listdir(SAMPLES):
            if not name.startswith("bad_") or name.endswith(".txt"):
                continue
            with self.subTest(name=name):
                with open(os.path.join(SAMPLES, name), "rb") as f:
                    raw = f.read()
                try:
                    m = h.parse(raw)
                except h.HL7Error:
                    continue
                try:
                    conv = convert(m)
                except MappingError:
                    continue
                self.assertTrue(errors(validate_bundle(conv.bundle)), f"{name} should have failed mapping or validation")

    def test_not_hl7_fails_to_parse(self):
        import os

        from tests.helpers import SAMPLES
        with open(os.path.join(SAMPLES, "bad_not_hl7.txt"), "rb") as f:
            with self.assertRaises(h.HL7Error):
                h.parse(f.read())


if __name__ == "__main__":
    unittest.main()
