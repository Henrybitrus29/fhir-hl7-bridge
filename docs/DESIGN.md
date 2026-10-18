# Design notes

## Scope
HL7 v2 ORU^R01 (lab/diagnostic results) to FHIR R4, over MLLP. This is one well-bounded slice of interoperability work,
chosen because it has a clear right answer (the numbers either match the source message or they don't) and because
results feeds are one of the most common v2 interfaces still running in production.

## Why these decisions
- **Deterministic resource ids** (UUID v5 over natural keys: order numbers, OBX set id + code). Re-sending the same
  message is idempotent — it updates the same resources rather than creating duplicates — which matters because MLLP
  senders retry on any ACK that isn't `AA`.
- **Patient is `POST` with `ifNoneExist`** (conditional create), never `PUT`. A results feed must never overwrite
  demographics it does not own; ADT (admit/discharge/transfer) feeds own that data.
- **Reject rather than guess.** An unmapped OBX value type (e.g. `ED`, an embedded document), a missing patient
  identifier, or a message type other than ORU^R01 raises `MappingError` and the message is NAK'd (`AR`) and kept in the
  dead-letter store. A silently dropped or wrongly-typed lab result is a worse failure mode than a rejected message a
  human has to look at.
- **Code systems are never invented.** A coded value whose system isn't recognised (LOINC, SNOMED CT, ICD-10, CPT) gets
  a clearly-marked placeholder system (`urn:hl7v2:codesystem:...`) and a warning, not a guessed real one.
- **Decimal precision is preserved end to end** (`1.40` stays `"1.40"`, not `1.4`), using Python `Decimal` and a small
  JSON encoder (`fhirjson.py`) — trailing zeros in a lab value can be clinically meaningful.
- **Every message gets an ACK**, and every failure is dead-lettered with the reason and a hash of the control id (never
  the patient data) in the log. Nothing is ever silently lost; `hl7bridge replay` re-runs the dead-letter store once the
  underlying problem (a down FHIR server, a bad mapping rule you've since fixed) is resolved.
- **MLLP has no built-in security.** `docs/VALIDATION.md`'s sibling note in `mllp.py` says this directly: bind to
  localhost or a private network and put TLS (stunnel or similar) or a VPN in front of anything carrying real data.

## What's deliberately out of scope
ADT (patient demographics/encounters), orders going the other direction, HL7 v2 versions' full field set, and any
specific implementation guide's conformance requirements. See `docs/VALIDATION.md` for what "conformant" would require.
