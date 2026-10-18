import json
import logging
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from hl7bridge.pipeline import Pipeline
from hl7bridge.sinks import DeadLetter, FhirSink, FileSink
from tests.helpers import OBR, PID, msg, obx


class RecordingFhirHandler(BaseHTTPRequestHandler):
    log = None   # class-level list of (status_sent, body) set by caller
    script = None  # list of ints (status codes) popped in order; last one repeats

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        status = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        RecordingFhirHandler.log.append((status, json.loads(body)))
        self.send_response(status)
        self.send_header("Content-Type", "application/fhir+json")
        if status in (200, 201):
            payload = json.dumps({"resourceType": "Bundle", "type": "transaction-response", "entry": []}).encode()
        else:
            payload = json.dumps({"resourceType": "OperationOutcome", "issue": [{"severity": "error", "diagnostics": "boom"}]}).encode()
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def start_server(script):
    RecordingFhirHandler.log = []
    RecordingFhirHandler.script = list(script)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), RecordingFhirHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/fhir"


GOOD = msg(PID, OBR, obx())


class FileSinkTests(unittest.TestCase):
    def test_writes_a_file_per_bundle(self):
        with tempfile.TemporaryDirectory() as d:
            sink = FileSink(d)
            r1, r2 = sink.send({"resourceType": "Bundle"}), sink.send({"resourceType": "Bundle"})
            self.assertTrue(r1.ok and r2.ok)
            self.assertNotEqual(r1.detail, r2.detail)
            import os
            self.assertEqual(len(os.listdir(d)), 2)


class FhirSinkTests(unittest.TestCase):
    def test_success(self):
        srv, url = start_server([200])
        try:
            res = FhirSink(url, token="t").send({"resourceType": "Bundle", "type": "transaction", "entry": []})
            self.assertTrue(res.ok)
            self.assertEqual(RecordingFhirHandler.log[0][0], 200)
        finally:
            srv.shutdown()

    def test_auth_header_sent(self):
        srv, url = start_server([200])
        try:
            FhirSink(url, token="secret-token").send({"resourceType": "Bundle"})
        finally:
            srv.shutdown()

    def test_retries_on_500_then_succeeds(self):
        srv, url = start_server([500, 500, 200])
        try:
            res = FhirSink(url, attempts=3, backoff=0.01).send({"resourceType": "Bundle"})
            self.assertTrue(res.ok)
            self.assertEqual(len(RecordingFhirHandler.log), 3)
        finally:
            srv.shutdown()

    def test_persistent_500_is_retryable_failure(self):
        srv, url = start_server([500])
        try:
            res = FhirSink(url, attempts=2, backoff=0.01).send({"resourceType": "Bundle"})
            self.assertFalse(res.ok)
            self.assertTrue(res.retryable)
            self.assertEqual(len(RecordingFhirHandler.log), 2)
        finally:
            srv.shutdown()

    def test_400_is_not_retried(self):
        srv, url = start_server([400])
        try:
            res = FhirSink(url, attempts=5, backoff=0.01).send({"resourceType": "Bundle"})
            self.assertFalse(res.ok)
            self.assertFalse(res.retryable)
            self.assertEqual(len(RecordingFhirHandler.log), 1)
        finally:
            srv.shutdown()

    def test_network_error_is_retryable(self):
        res = FhirSink("http://127.0.0.1:1", attempts=2, backoff=0.01, timeout=1).send({"resourceType": "Bundle"})
        self.assertFalse(res.ok)
        self.assertTrue(res.retryable)


class DeadLetterTests(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            dl = DeadLetter(d)
            stem = dl.put(b"raw hl7 bytes", "map", "could not map it", "abc123", ["error: x"])
            self.assertEqual(dl.items(), [stem])
            self.assertEqual(dl.read(stem), b"raw hl7 bytes")
            dl.remove(stem)
            self.assertEqual(dl.items(), [])

    def test_files_are_owner_only(self):
        import os
        import stat
        with tempfile.TemporaryDirectory() as d:
            stem = DeadLetter(d).put(b"x", "parse", "bad")
            mode = stat.S_IMODE(os.stat(os.path.join(d, stem + ".hl7")).st_mode)
            self.assertEqual(mode, 0o600)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        logging.disable(logging.NOTSET)

    def test_good_message_acked_aa_and_delivered(self):
        with tempfile.TemporaryDirectory() as out, tempfile.TemporaryDirectory() as dead:
            pipe = Pipeline(FileSink(out), DeadLetter(dead))
            outcome, ack = pipe.process(GOOD.encode())
            self.assertEqual(outcome.code, "AA")
            self.assertIn(b"MSA|AA", ack)
            import os
            self.assertEqual(len(os.listdir(out)), 1)
            self.assertEqual(dl_items := os.listdir(dead), [])

    def test_unparseable_message_acked_ar_and_dead_lettered(self):
        with tempfile.TemporaryDirectory() as out, tempfile.TemporaryDirectory() as dead:
            pipe = Pipeline(FileSink(out), DeadLetter(dead))
            outcome, ack = pipe.process(b"not hl7 at all")
            self.assertEqual(outcome.code, "AR")
            self.assertIn(b"MSA|AR", ack)
            self.assertEqual(len(DeadLetter(dead).items()), 1)

    def test_unmappable_message_acked_ar(self):
        bad = msg(PID.replace("MRN1^^^HOSP^MR", ""), OBR, obx())
        with tempfile.TemporaryDirectory() as out, tempfile.TemporaryDirectory() as dead:
            outcome, ack = Pipeline(FileSink(out), DeadLetter(dead)).process(bad.encode())
            self.assertEqual(outcome.code, "AR")

    def test_sink_failure_retryable_gives_ae(self):
        srv, url = start_server([500])
        try:
            with tempfile.TemporaryDirectory() as dead:
                pipe = Pipeline(FhirSink(url, attempts=1), DeadLetter(dead))
                outcome, ack = pipe.process(GOOD.encode())
                self.assertEqual(outcome.code, "AE")
                self.assertIn(b"MSA|AE", ack)
                self.assertEqual(len(DeadLetter(dead).items()), 1)
        finally:
            srv.shutdown()

    def test_sink_failure_permanent_gives_ar(self):
        srv, url = start_server([400])
        try:
            with tempfile.TemporaryDirectory() as dead:
                pipe = Pipeline(FhirSink(url, attempts=1), DeadLetter(dead))
                outcome, _ = pipe.process(GOOD.encode())
                self.assertEqual(outcome.code, "AR")
        finally:
            srv.shutdown()

    def test_control_id_echoed_in_ack(self):
        with tempfile.TemporaryDirectory() as out, tempfile.TemporaryDirectory() as dead:
            outcome, ack = Pipeline(FileSink(out), DeadLetter(dead)).process(GOOD.encode())
            self.assertIn(b"MSA|AA|T-1", ack)

    def test_replay_processes_and_clears_dead_letters(self):
        with tempfile.TemporaryDirectory() as out, tempfile.TemporaryDirectory() as dead:
            pipe = Pipeline(FileSink(out), DeadLetter(dead))
            pipe.process(b"garbage 1")
            pipe.process(b"garbage 2")
            self.assertEqual(len(DeadLetter(dead).items()), 2)
            result = pipe.replay()
            self.assertEqual(result, {"replayed_ok": 0, "still_failing": 2})

            srv, url = start_server([200])
            try:
                pipe2 = Pipeline(FhirSink(url), DeadLetter(dead))
                pipe2.dead.put(GOOD.encode(), "deliver", "simulated earlier failure")
                result2 = pipe2.replay()
                self.assertEqual(result2["replayed_ok"], 1)
                self.assertEqual(len(DeadLetter(dead).items()), 2)   # the two garbage messages remain
            finally:
                srv.shutdown()

    def test_no_patient_data_in_logs(self):
        import io
        logging.disable(logging.NOTSET)
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        log = logging.getLogger("hl7bridge")
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        try:
            with tempfile.TemporaryDirectory() as out, tempfile.TemporaryDirectory() as dead:
                Pipeline(FileSink(out), DeadLetter(dead)).process(GOOD.encode())
        finally:
            log.removeHandler(handler)
            logging.disable(logging.CRITICAL)
        self.assertNotIn("TESTPATIENT", stream.getvalue())
        self.assertNotIn("MRN1", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
