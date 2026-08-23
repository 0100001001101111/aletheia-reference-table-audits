#!/usr/bin/env python3
"""R4 classification v3 (2026-08-23) — conflicts-clause pass.

Identical to v2 except the frozen R5 clause 'or evidence conflicts' now
executes mechanically BEFORE the mixing rule: a record whose lineage contains
a consistent placement only at a different initial level while the same
initial level's placement is inconsistent in a source dataset is conflicted
evidence and classes EVIDENCE_AMBIGUOUS (per the Codex R4 re-verification).
Still POST_OUTCOME_EXPLORATORY, claim_authority NONE.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROUTE = Path("/data/adp/investigations/lab_bench_hunt_2026-08-22/04_routes/R4_FLAG_ADJUDICATION")
SRC = ROUTE / "receipts" / "EVIDENCE_V2_FLAGRES.json"
OUT = ROUTE / "receipts" / "ADJUDICATION_V3.json"

ENERGY_FIT = re.compile(
    r"poor(ly)?\s+(energy\s+)?fit|omitted\s+(from|in)\s+the\s+fitting|"
    r"differs?\s+by\s+\d+\s*\|?s|level-energy\s+difference|"
    r"fits\s+placement\s+poorly|deviates\s+by|excluded\s+from\s+least-?squares",
    re.IGNORECASE)
SOURCE_DEF = re.compile(r"E\([A-Za-z]\)\s*\$?\s*From", re.IGNORECASE)

OVERRIDES = {
    ("60NI", "613.7"): {
        "strip_r1": True,
        "reason": "the attached comment 'M$d not consistent with |DJ|p' addresses the mixing-ratio/multipolarity, not the gamma energy arithmetic",
    },
}


def conflicted(p):
    hits = p["lineage"]
    cons_same = any(h["state"] == "CONSISTENT_PLACED" and h["same_initial_as_adopted"]
                    for h in hits)
    cons_other = any(h["state"] == "CONSISTENT_PLACED" and not h["same_initial_as_adopted"]
                     for h in hits)
    incons_same = any(h["state"] == "INCONSISTENT_PLACED" and h["same_initial_as_adopted"]
                      for h in hits)
    return (not cons_same) and cons_other and incons_same


def classify(p):
    f = p["flag"]
    key = (f["nucid"], f["gamma"])
    r1_hits = []
    for c in p["attached_comments"] + p["whole_dataset_hits"]["energy_string"]:
        if ENERGY_FIT.search(c["text"][9:]):
            r1_hits.append({"kind": "comment", "lineno": c["lineno"],
                            "text": c["text"].rstrip()})
    gamma_letters = set()
    if p.get("col77", " ").strip():
        gamma_letters.add(p["col77"])
    for c in p["attached_comments"]:
        if " G FLAG=" in c["text"] or c["text"][7:9].strip() == "G":
            for m in re.finditer(r"FLAG=([A-Za-z]+)", c["text"]):
                gamma_letters.update(m.group(1))
    for rdef in p.get("resolved_flag_definitions", []):
        if rdef["letter"] in gamma_letters and ENERGY_FIT.search(rdef["text"][9:]):
            r1_hits.append({"kind": "footnote_definition", "letter": rdef["letter"],
                            "lineno": rdef["lineno"], "text": rdef["text"].rstrip()})
    ov = OVERRIDES.get(key)
    if r1_hits and not (ov and ov.get("strip_r1")):
        return "DOCUMENTED_OUTLIER", r1_hits, None
    # frozen R5 conflicts clause executes before mixing
    if conflicted(p):
        chits = [h for h in p["lineage"] if h["state"] in
                 ("CONSISTENT_PLACED", "INCONSISTENT_PLACED")][:6]
        return ("EVIDENCE_AMBIGUOUS", chits,
                "conflicted lineage: consistent only at a different initial level while the same initial level is inconsistent in a source (frozen R5 clause)")
    ls = p["lineage_summary"]
    consistent = ls["consistent_placed_same_initial"] + ls["consistent_placed_other_initial"]
    caveat = None
    if consistent > 0:
        if ls["consistent_placed_same_initial"] == 0:
            caveat = "every consistent placement sits at a different initial level; wrong-attachment possibility flagged for follow-up"
        hits = [h for h in p["lineage"] if h["state"] == "CONSISTENT_PLACED"]
        return "SOURCE_SCHEME_MIXING", hits[:6], caveat
    src_defs = [r for r in p.get("resolved_flag_definitions", [])
                if SOURCE_DEF.search(r["text"][9:])]
    if src_defs:
        return "SOURCE_SCHEME_MIXING", src_defs, "documented source attribution; no consistent lineage placement located"
    neg = p["whole_dataset_search_receipt"]["negative"]["energy_string"]
    if neg and consistent == 0:
        return ("BOOKKEEPING_ERROR_CANDIDATE",
                [{"kind": "negative_search_receipt",
                  "receipt": p["whole_dataset_search_receipt"]},
                 {"kind": "lineage_summary", "summary": ls}], None)
    return "EVIDENCE_AMBIGUOUS", [], None


def main() -> None:
    d = json.loads(SRC.read_text())
    rows = []
    for p in d["packets"]:
        cls, evid, caveat = classify(p)
        f = p["flag"]
        rows.append({"nucid": f["nucid"], "lineno": f["lineno"],
                     "raw_sha256": f["raw_sha256"], "relation": f["relation"],
                     "gamma": f["gamma"], "initial_level": f["initial_level"],
                     "deviation_kev": f.get("deviation_kev", f.get("min_deviation_kev")),
                     "class": cls, "evidence": evid, "caveat": caveat,
                     "mechanical_class": p["mechanical_class"],
                     "override": OVERRIDES.get((f["nucid"], f["gamma"]))})
    from collections import Counter
    census = dict(Counter(r["class"] for r in rows))
    payload = {"schema": "aletheia.r4-adjudication.classifications.v3",
               "authority": "POST_OUTCOME_EXPLORATORY",
               "claim_authority": "NONE",
               "rule_set": __doc__,
               "evidence_receipt_sha256": hashlib.sha256(SRC.read_bytes()).hexdigest(),
               "classifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "census": census, "rows": rows}
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps({"census": census, "out": str(OUT)}))


if __name__ == "__main__":
    main()
