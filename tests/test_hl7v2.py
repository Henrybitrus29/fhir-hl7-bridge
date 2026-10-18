import unittest

from hl7bridge import hl7v2 as h
from tests.helpers import msg, PID, OBR, obx


class ParserTests(unittest.TestCase):
    def test_basic_access_and_components(self):
        m = h.parse(msg(PID))
        self.assertEqual(m.message_type, "ORU^R01")
        self.assertEqual(m.control_id, "T-1")
        self.assertEqual(m.first("PID").get(5, 1), "TESTPATIENT")
        self.assertEqual(m.first("PID").get(3, 4), "HOSP")
        self.assertEqual(m.msh.get(2), "^~\\&")

    def test_custom_delimiters(self):
        raw = "MSH|*~\\&|A|B|C|D|20260101||ORU*R01|X1|P|2.5\rPID|1||9*~*~*H**MR||DOE*JOHN\r"
        m = h.parse(raw)
        self.assertEqual(m.message_type, "ORU^R01")
        self.assertEqual(m.first("PID").get(5, 2), "JOHN")

    def test_repetitions(self):
        m = h.parse(msg("PID|1||A1^^^X^MR~B2^^^Y^PI||N"))
        pid = m.first("PID")
        self.assertEqual(pid.reps(3), 2)
        self.assertEqual(pid.get(3, 1, rep=2), "B2")
        self.assertEqual(pid.get(3, 1, rep=3), "")

    def test_escape_sequences(self):
        d = h.Delims()
        self.assertEqual(h.unescape(r"a\F\b\S\c\T\d\R\e\E\f", d), "a|b^c&d~e\\f")
        self.assertEqual(h.unescape(r"line1\.br\line2", d), "line1\nline2")
        self.assertEqual(h.unescape("\\X41\\\\X42\\", d), "AB")
        self.assertEqual(h.unescape(r"\Zunknown\ stays", d), r"\Zunknown\ stays")
        self.assertEqual(h.unescape("unterminated \\F", d), "unterminated \\F")

    def test_escaped_delimiter_does_not_split_fields(self):
        m = h.parse(msg(r"NTE|1||a\F\b\S\c"))
        self.assertEqual(m.first("NTE").get(3), "a|b^c")

    def test_newline_variants(self):
        for sep in ("\r", "\n", "\r\n"):
            raw = f"MSH|^~\\&|A|B|C|D|2026||ORU^R01|X|P|2.5{sep}PID|1||1^^^H^MR{sep}"
            self.assertEqual(len(h.parse(raw).segments), 2)

    def test_latin1_fallback(self):
        raw = "MSH|^~\\&|A|B|C|D|2026||ORU^R01|X|P|2.5\rPID|1||1||M\xfcller^Jos\xe9\r".encode("latin-1")
        self.assertEqual(h.parse(raw).first("PID").get(5, 1), "Müller")

    def test_rejects_bad_input(self):
        for bad in ("", "hello", "PID|1||x", "MSH", "MSH||||\r"):
            with self.assertRaises(h.HL7Error, msg=repr(bad)):
                h.parse(bad)
        with self.assertRaises(h.HL7Error):
            h.parse("MSH|^~\\&|A|B|C|D|2026||ORU^R01|X|P|2.5\rbad segment\r")
        with self.assertRaises(h.HL7Error):
            h.parse(b"MSH|^~\\&" + b"x" * (h.MAX_MESSAGE_BYTES + 1))


class TimestampTests(unittest.TestCase):
    def test_precisions(self):
        self.assertEqual(h.hl7_ts("2026"), ("2026", "year"))
        self.assertEqual(h.hl7_ts("202603"), ("2026-03", "month"))
        self.assertEqual(h.hl7_ts("20260314"), ("2026-03-14", "day"))
        self.assertEqual(h.hl7_ts("202603141530"), ("2026-03-14T15:30:00+00:00", "minute"))
        self.assertEqual(h.hl7_ts("20260314153045.123-0500"), ("2026-03-14T15:30:45.123-05:00", "second"))

    def test_default_timezone(self):
        self.assertEqual(h.hl7_ts("20260314153045", "+0100")[0], "2026-03-14T15:30:45+01:00")

    def test_invalid(self):
        for bad in ("20261340", "20260230", "2026031425", "abc", "20260314246000", "202613"):
            self.assertIsNone(h.hl7_ts(bad), bad)


class MllpTests(unittest.TestCase):
    def test_framing_across_chunks_and_noise(self):
        u = h.Unframer()
        a, b = h.frame(b"ONE"), h.frame(b"TWO")
        self.assertEqual(u.feed(b"noise" + a[:4]), [])
        self.assertEqual(u.feed(a[4:] + b), [b"ONE", b"TWO"])
        self.assertEqual(u.feed(b""), [])

    def test_oversize_frame_raises(self):
        u = h.Unframer(limit=50)
        with self.assertRaises(h.HL7Error):
            u.feed(h.SB + b"x" * 200)

    def test_ack_codes_and_sanitised_text(self):
        m = h.parse(msg(PID, ctrl="CTRL-9"))
        ack = h.build_ack(m, "AR", "bad | field ^ here").decode()
        self.assertIn("MSA|AR|CTRL-9|bad   field   here", ack)
        self.assertTrue(ack.startswith("MSH|^~\\&|EHR|GENERAL_HOSP|LABSYS|CENTRAL_LAB|"))
        self.assertIn("ACK^R01", ack)
        anon = h.build_ack(None, "AR", "garbage").decode()
        self.assertIn("MSA|AR||garbage", anon)


if __name__ == "__main__":
    unittest.main()
