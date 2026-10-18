# Validation: what is checked, by what, and what is NOT verified

Three layers exist; only the first two have actually been run.

## Layer 1: `fhir.resources` (Pydantic models), always on
Generated from HL7's official FHIR R4B schemas. Checks resource structure, required elements, cardinality and primitive
formats (a bad date format is rejected; a `status` of `"banana"` is NOT, because this layer does not check code bindings).

## Layer 2: `hl7bridge/validate.py`, always on
Hand-written checks this project adds on top of layer 1:
- required code bindings for `status`/`intent`/`gender` (the values FHIR calls "required" binding strength)
- every `reference` inside the bundle resolves to another entry in the same bundle
- no duplicate `fullUrl` or resource id, and a `PUT` url matches the resource's own id
- an `Observation` has exactly one of a value or a `dataAbsentReason`
- result and birth dates are not in the future
- a `final`/`corrected` `DiagnosticReport` with no results and no conclusion is a warning, not an error

Run: `python -m unittest tests.test_validate` (18 tests, all passing).

## Layer 3: the official HAPI `validator_cli.jar` — NOT run yet
I downloaded `validator_cli.jar` to try it as a second, independent check. It needs to fetch the `hl7.fhir.r4.core`
definitions package from the FHIR package registry (`packages.fhir.org` / `packages2.fhir.org`), and that host was not on
the network I had access to while building this. I could not get it to run
offline here, and I am not claiming it passed. Before you rely on this project, run it yourself:

```bash
curl -L -o validator_cli.jar https://github.com/hapifhir/org.hl7.fhir.core/releases/latest/download/validator_cli.jar
java -jar validator_cli.jar /tmp/*.json -version 4.0.1 -tx n/a    # -tx n/a skips terminology/code lookups
```
This is the standard reference validator used across the FHIR community; running it, and fixing whatever it finds that
layers 1-2 did not, is the natural next step before calling this project's output "conformant."

## What none of the three layers prove
- **Semantic correctness** beyond the rules above: that a sodium value of 138 is actually right, or that a LOINC code
  genuinely matches the test the lab performed. That is a clinical data-quality question, not a schema one.
- **A specific implementation guide**, such as the HL7 v2-to-FHIR IG or a national core profile. This project is
  loosely inspired by the HL7 v2-to-FHIR approach for field mapping choices but makes no conformance claim to it.
- **Interaction with a real FHIR server's business rules** (its own required extensions, its own terminology, its own
  auth). `hl7bridge push` and `hl7bridge serve --fhir-base` have only been tested against a local mock HTTP
  server (`tests/test_pipeline.py`), never against a real server such as HAPI's public test server or a vendor sandbox.
