import os

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "samples")


def sample(name: str) -> bytes:
    with open(os.path.join(SAMPLES, name), "rb") as f:
        return f.read()


def seg(name, fields):
    n = max(fields) if fields else 0
    arr = [""] * (n + 1)
    for k, v in fields.items():
        arr[k] = v
    return name + "|" + "|".join(arr[1:])


def msg(*segments, mtype="ORU^R01^ORU_R01", proc="P", ctrl="T-1"):
    head = f"MSH|^~\\&|LABSYS|CENTRAL_LAB|EHR|GENERAL_HOSP|20260314083512||{mtype}|{ctrl}|{proc}|2.5.1"
    return "\r".join([head, *segments]) + "\r"


PID = seg("PID", {1: "1", 3: "MRN1^^^HOSP^MR", 5: "TESTPATIENT^ALEX", 7: "19800214", 8: "M"})
OBR = seg("OBR", {1: "1", 2: "P1", 3: "F1", 4: "51990-0^BMP^LN", 7: "20260314075500+0000", 25: "F"})


def obx(i=1, typ="NM", code="2951-2^Sodium^LN", val="140", unit="mmol/L", rng="", flag="", status="F"):
    return seg("OBX", {1: str(i), 2: typ, 3: code, 5: val, 6: unit, 7: rng, 8: flag, 11: status})


def entries(bundle, rtype):
    return [e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == rtype]
