# Setup

```bash
pip install -r requirements.txt
```

## Convert one file and see validation results
```bash
python -m hl7bridge convert samples/oru_bmp.hl7 --out /tmp/bundle.json
```

## Run the MLLP receiver
```bash
# writes each successful bundle as a file (good for a first look):
python -m hl7bridge serve --port 2575 --outbox outbox --dead-letter dead-letter

# or push straight to a FHIR server:
export FHIR_TOKEN=...   # if the server needs a bearer token
python -m hl7bridge serve --port 2575 --fhir-base https://your-fhir-server/fhir --dead-letter dead-letter
```
Send it a message with any MLLP-capable tool, for example `hl7-mllp-client`, or your lab system's test harness pointed
at `127.0.0.1:2575`.

## Re-process failures once the cause is fixed
```bash
python -m hl7bridge replay --fhir-base https://your-fhir-server/fhir --dead-letter dead-letter
```

## Map an unfamiliar sending system's identifiers
Unknown assigning authorities get a clearly-marked placeholder system and a warning. To use real identifier systems,
pass a JSON file:
```json
{ "GENERAL_HOSP": "https://your-org.example/patient-ids", "CENTRAL_LAB": "https://your-org.example/order-ids" }
```
```bash
python -m hl7bridge convert samples/oru_bmp.hl7 --system-map systems.json
```

## Try the SMART on FHIR demo app
`smart-app/index.html` is a single-file SMART App Launch client (patient demographics + recent labs). It was written
and reviewed but **not exercised against a live server** — I had no browser available to test it. To try it:
1. Host the file anywhere static files are served (even `python -m http.server` on your machine).
2. Open https://launch.smarthealthit.org, choose "Provider EHR Launch" (or Patient), and set the launch URL to your
   hosted `index.html`.
3. Pick a sample patient in the launcher. You should see demographics and, if the chosen patient has lab Observations
   in the sandbox's data, a short results list.

## Get synthetic test data (Synthea)
```bash
git clone https://github.com/synthetichealth/synthea.git && cd synthea
./run_synthea -p 20   # generates FHIR Bundles for 20 synthetic patients in ./output/fhir
```
Synthea outputs FHIR, not HL7 v2; it's listed here as the standard source of realistic *synthetic* patients for
testing against a FHIR server directly (e.g. with `hl7bridge push`), separately from this project's HL7-to-FHIR path.

## Running the HAPI validator yourself (layer 3)
See `docs/VALIDATION.md` — not run because the package registry it needs wasn't reachable from where I built this.
