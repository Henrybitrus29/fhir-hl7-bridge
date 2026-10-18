# HL7 v2 to FHIR R4 bridge

Converts HL7 v2 ORU^R01 (lab/diagnostic result) messages to FHIR R4, over an MLLP receiver or a one-shot CLI. Built as a
portfolio project for healthcare interoperability work (the kind driven by the CMS Interoperability and Prior
Authorization rule and similar FHIR mandates) — **synthetic data only, nowhere does this touch real patient data.**

```
HL7 v2 (MLLP) -> parse -> map -> validate -> FHIR server (or file)
                                      |
                                dead-letter store (every failure, with the reason)
```

## What's here
| Path | What it is |
|---|---|
| `hl7bridge/hl7v2.py` | HL7 v2 parser, MLLP framing, ACK builder — no third-party dependencies |
| `hl7bridge/mapper.py` | ORU^R01 -> FHIR `Bundle` (Patient, ServiceRequest, DiagnosticReport, Observation) |
| `hl7bridge/validate.py` | Two-layer validation (see `docs/VALIDATION.md`) |
| `hl7bridge/pipeline.py` | parse -> map -> validate -> deliver, with an ACK and dead-letter entry for every outcome |
| `hl7bridge/mllp.py` | asyncio MLLP server |
| `hl7bridge/sinks.py` | write to files, or POST a transaction Bundle to a FHIR server, with retry logic |
| `hl7bridge/cli.py` | `convert`, `serve`, `push`, `replay` |
| `smart-app/index.html` | SMART App Launch demo client (patient demographics + recent labs) — see caveat below |
| `samples/` | 3 realistic synthetic ORU messages, 6 deliberately invalid ones |
| `docs/DESIGN.md`, `docs/VALIDATION.md`, `docs/SETUP.md` | design rationale, exactly what is and isn't verified, how to run it |

## Try it
```bash
pip install -r requirements.txt
python -m hl7bridge convert samples/oru_bmp.hl7 --out /tmp/bundle.json
python -m unittest discover -s tests -t .
```

## Status: what I've verified myself, and what I haven't
- **104 automated tests pass** — parser (14), mapper (48), validator (18), pipeline/sinks (17), real asyncio MLLP server
  over real TCP sockets (7) — covering the included samples, malformed input, retries, dead-lettering and replay.
- **Validation layer 3 (the official HAPI `validator_cli.jar`) did not run here** — the FHIR package registry it needs
  was outside the network I had access to. `docs/VALIDATION.md` explains exactly what that means and gives the
  two commands to run it yourself.
- **The SMART app was written and reviewed, not run** — I had no browser available to test it. Launch it from
  https://launch.smarthealthit.org as described in `docs/SETUP.md` before you demo it.
- **Never tested against a real EHR, a real FHIR server, or real patient data of any kind.**

## Not implemented
ADT (demographics/admit-discharge-transfer) feeds, HL7 v2 message types other than ORU^R01, and conformance to any
specific implementation guide (the mapping is loosely informed by the HL7 v2-to-FHIR approach, not certified against
it — see `docs/VALIDATION.md`).
