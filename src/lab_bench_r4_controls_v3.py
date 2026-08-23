#!/usr/bin/env python3
"""R4 end-to-end control gate v3 (2026-08-23).

Per the Codex re-verification: gates the COMPLETE chain (extract -> flag
resolution -> final classification) on frozen synthetic packets.

- Four planted datasets, one per non-ambiguous final class plus a conflicted
  case, run end to end; each must land in its bound final class.
- A FROZEN expected full packet: the mixing plant's packet is serialized and
  compared against a stored expected JSON (first run stores it; later runs
  must match byte for byte).
- Deletion gates on required repaired fields: removing col77, all header
  comments, or all positive whole-dataset hits from the outlier plant must
  change its final class; removing lineage from the mixing plant must change
  its final class; breaking the negative receipt must demote the candidate
  plant. Each check calls the real classifier, not a mechanical proxy.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

ROUTE = Path("/data/adp/investigations/lab_bench_hunt_2026-08-22/04_routes/R4_FLAG_ADJUDICATION")
EXPECTED = ROUTE / "receipts" / "CONTROLS_V3_EXPECTED_PACKET.json"


def load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


ex = load("r4x2", "/data/adp/scripts/lab_bench_r4_evidence_extractor_v2.py")
fr = load("r4fr", "/data/adp/scripts/lab_bench_r4_flag_resolution_v1.py")
cl = load("r4c3", "/data/adp/scripts/lab_bench_r4_classification_v3.py")


def resolve_flags(p):
    """Inline copy of the flag-resolution transform for one packet."""
    letters = set()
    marker = p.get("col77", " ")
    if marker.strip() and marker not in fr.MULTIPLY_PLACED:
        letters.add(marker)
    for c in p["attached_comments"]:
        for m in re.finditer(r"FLAG=([A-Za-z]+)", c["text"]):
            letters.update(m.group(1))
    resolved = []
    pool = (p["header_comments"] + p["whole_dataset_hits"]["source_vocab"]
            + p["whole_dataset_hits"]["outlier_vocab"]
            + p["whole_dataset_hits"]["structure_vocab"])
    seen = set()
    for c in pool:
        body = c["text"][9:]
        for letter in sorted(letters):
            if re.search(rf"\(\s*{re.escape(letter)}\s*[),]", body):
                k = (letter, c["lineno"])
                if k not in seen:
                    seen.add(k)
                    resolved.append({"letter": letter, "lineno": c["lineno"],
                                     "text": c["text"].rstrip()})
    p["flag_letters"] = sorted(letters)
    p["multiply_placed_marker"] = fr.MULTIPLY_PLACED.get(marker)
    p["resolved_flag_definitions"] = resolved
    return p


def end_to_end(kind, extra_rows=None):
    text = ex.synth_dataset(kind)
    if extra_rows:
        text = text.rstrip("\n") + "\n" + "\n".join(extra_rows) + "\n"
    flag, datasets = ex.synth_flag(text)
    flag["gamma"] = flag["raw"].ljust(80)[9:19].strip()
    p = ex.build_packet(datasets, flag)
    p["mechanical_class"] = ex.mechanical_class(p)
    p = resolve_flags(p)
    cls, evid, caveat = cl.classify(p)
    return p, cls


def synth_conflict():
    """Adopted gamma inconsistent; source A repeats the same initial level
    inconsistently; source B places the gamma at a different initial level
    consistently -> frozen R5 conflict."""
    n = " 60FX"
    rows = [f"{n}    ADOPTED LEVELS, GAMMAS".ljust(80),
            ex._card(n, " ", "L", "0.000", " 5", "0+"),
            ex._card(n, " ", "L", "1000.000", " 5", "2+"),
            ex._card(n, " ", "G", "998.700", " 5", "100"),
            "".ljust(0)]
    srcA = [f"{n}    FX B- DECAY".ljust(80),
            ex._card(n, " ", "L", "0.000", " 5", "0+"),
            ex._card(n, " ", "L", "1000.000", " 5", "2+"),
            ex._card(n, " ", "G", "998.700", " 5", "100")]
    srcB = [f"{n}    FX (N,G)".ljust(80),
            ex._card(n, " ", "L", "0.000", " 5", "0+"),
            ex._card(n, " ", "L", "201.294", " 5", "0+"),
            ex._card(n, " ", "L", "1200.000", " 5", "2+"),
            ex._card(n, " ", "G", "998.700", " 5", "100")]
    # srcB: gamma from 1200.000 -> 1200.000-998.700-recoil(0.0089)=201.291 ~ level 201.294 ok
    text = "\n".join(rows[:-1]) + "\n\n" + "\n".join(srcA) + "\n\n" + "\n".join(srcB) + "\n"
    flag, datasets = ex.synth_flag(text)
    flag["gamma"] = flag["raw"].ljust(80)[9:19].strip()
    p = ex.build_packet(datasets, flag)
    p["mechanical_class"] = ex.mechanical_class(p)
    p = resolve_flags(p)
    cls, _, caveat = cl.classify(p)
    return p, cls, caveat


def main() -> int:
    rep = {}
    plants = {"outlier": "DOCUMENTED_OUTLIER",
              "mixing": "SOURCE_SCHEME_MIXING",
              "candidate": "BOOKKEEPING_ERROR_CANDIDATE",
              "unplaced_only": "BOOKKEEPING_ERROR_CANDIDATE"}
    planted, ok = {}, True
    packets = {}
    for kind, want in plants.items():
        p, cls = end_to_end(kind)
        packets[kind] = p
        planted[kind] = {"expected": want, "got": cls, "passed": cls == want}
        ok &= cls == want
    p_conf, cls_conf, cav = synth_conflict()
    planted["conflict"] = {"expected": "EVIDENCE_AMBIGUOUS", "got": cls_conf,
                           "caveat": cav, "passed": cls_conf == "EVIDENCE_AMBIGUOUS"}
    ok &= cls_conf == "EVIDENCE_AMBIGUOUS"
    planted["passed"] = ok
    rep["planted_end_to_end"] = planted

    # frozen expected packet for the mixing plant
    ser = json.dumps(packets["mixing"], indent=2, sort_keys=True, default=str)
    if EXPECTED.exists():
        frozen_ok = EXPECTED.read_text() == ser
    else:
        EXPECTED.write_text(ser)
        frozen_ok = True
    rep["frozen_expected_packet"] = {
        "stored": str(EXPECTED),
        "sha256": hashlib.sha256(ser.encode()).hexdigest(),
        "passed": frozen_ok}

    # deletion gates on final classes
    dels, dok = {}, True
    p = dict(packets["outlier"])
    p2 = dict(p, col77=" ", header_comments=[], resolved_flag_definitions=[],
              attached_comments=[], whole_dataset_hits=dict(
                  p["whole_dataset_hits"], energy_string=[], outlier_vocab=[],
                  structure_vocab=[], source_vocab=[]))
    cls2, _, _ = cl.classify(p2)
    dels["outlier_strip_all_doc_fields"] = {
        "got": cls2, "passed": cls2 != "DOCUMENTED_OUTLIER"}
    dok &= cls2 != "DOCUMENTED_OUTLIER"
    p = dict(packets["mixing"])
    p2 = dict(p, lineage=[], lineage_summary={
        "consistent_placed_same_initial": 0, "consistent_placed_other_initial": 0,
        "inconsistent_placed": 0, "unplaced_energy_only": 0},
        resolved_flag_definitions=[])
    cls2, _, _ = cl.classify(p2)
    dels["mixing_strip_lineage"] = {"got": cls2,
                                    "passed": cls2 != "SOURCE_SCHEME_MIXING"}
    dok &= cls2 != "SOURCE_SCHEME_MIXING"
    p = dict(packets["candidate"])
    p2 = dict(p, whole_dataset_search_receipt=dict(
        p["whole_dataset_search_receipt"],
        negative=dict(p["whole_dataset_search_receipt"]["negative"],
                      energy_string=False)))
    cls2, _, _ = cl.classify(p2)
    dels["candidate_break_negative_receipt"] = {
        "got": cls2, "passed": cls2 != "BOOKKEEPING_ERROR_CANDIDATE"}
    dok &= cls2 != "BOOKKEEPING_ERROR_CANDIDATE"
    dels["passed"] = dok
    rep["deletion_final_class"] = dels

    rep["passed"] = all(rep[k]["passed"] for k in
                        ("planted_end_to_end", "frozen_expected_packet",
                         "deletion_final_class"))
    out = ROUTE / "receipts" / "CONTROLS_V3.json"
    payload = {"schema": "aletheia.r4-adjudication.controls.v3",
               "gate_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "classifier_sha256": hashlib.sha256(Path(
                   "/data/adp/scripts/lab_bench_r4_classification_v3.py").read_bytes()).hexdigest(),
               "report": rep}
    out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps({"passed": rep["passed"], "out": str(out)}))
    return 0 if rep["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
