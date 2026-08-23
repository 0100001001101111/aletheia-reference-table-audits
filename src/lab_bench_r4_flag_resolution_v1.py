#!/usr/bin/env python3
"""R4 footnote-flag resolution v1 (2026-08-23).

For each EVIDENCE_V2 packet, resolve the record's footnote letters (col-77
marker and FLAG= tokens on G/L continuations) against the dataset's header
footnote definitions (E(<letter>), RI(<letter>), M(<letter>) comment cards),
attaching each resolved definition with its line receipt. Purely mechanical;
writes EVIDENCE_V2_FLAGRES.json for the classification layer.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROUTE = Path("/data/adp/investigations/lab_bench_hunt_2026-08-22/04_routes/R4_FLAG_ADJUDICATION")
SRC = ROUTE / "receipts" / "EVIDENCE_V2.json"
OUT = ROUTE / "receipts" / "EVIDENCE_V2_FLAGRES.json"

MULTIPLY_PLACED = {"&": "multiply placed, intensity not divided (format manual G-record col 77)",
                   "M": "multiply placed, intensity suitably divided (format manual G-record col 77)"}


def main() -> None:
    d = json.loads(SRC.read_text())
    for p in d["packets"]:
        letters = set()
        marker = p.get("col77", " ")
        if marker.strip() and marker not in MULTIPLY_PLACED:
            letters.add(marker)
        for c in p["attached_comments"]:
            for m in re.finditer(r"FLAG=([A-Za-z]+)", c["text"]):
                letters.update(m.group(1))
        resolved = []
        for c in p["header_comments"] + p["whole_dataset_hits"]["source_vocab"] \
                + p["whole_dataset_hits"]["outlier_vocab"] \
                + p["whole_dataset_hits"]["structure_vocab"]:
            body = c["text"][9:]
            for letter in sorted(letters):
                if re.search(rf"\(\s*{re.escape(letter)}\s*[),]", body):
                    resolved.append({"letter": letter, "lineno": c["lineno"],
                                     "text": c["text"].rstrip()})
        # dedupe
        seen = set()
        uniq = []
        for r in resolved:
            k = (r["letter"], r["lineno"])
            if k not in seen:
                seen.add(k)
                uniq.append(r)
        p["flag_letters"] = sorted(letters)
        p["multiply_placed_marker"] = MULTIPLY_PLACED.get(marker)
        p["resolved_flag_definitions"] = uniq
    d["schema"] = "aletheia.r4-adjudication.evidence.v2-flagres"
    d["flag_resolution_script_sha256"] = hashlib.sha256(
        Path(__file__).read_bytes()).hexdigest()
    OUT.write_text(json.dumps(d, indent=2, sort_keys=True, default=str) + "\n")
    n = sum(1 for p in d["packets"] if p["resolved_flag_definitions"])
    print(json.dumps({"packets": len(d["packets"]),
                      "with_resolved_definitions": n, "out": str(OUT)}))


if __name__ == "__main__":
    main()
