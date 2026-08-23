#!/usr/bin/env python3
"""R3_AME_EDITION_CHECK verifier v2 (2026-08-23).

Post-review repair per PREREG_AMENDMENT_V2.json: P0 is a rounding-compatibility
test enforced structurally before any verdict (C656); controls and score run
from these same bytes; the separable-row leaning is reported descriptively.
Reuses v1's parsers and extraction; verdict logic reimplemented here.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import socket
import sys
from fractions import Fraction
from pathlib import Path

_s = importlib.util.spec_from_file_location(
    "r3v1", "/data/adp/scripts/lab_bench_r3_edition_check_v1.py")
r3 = importlib.util.module_from_spec(_s)
_s.loader.exec_module(r3)

ROUTE = r3.ROUTE
K = r3.K
ROWS = r3.ROWS
KNOWN = r3.KNOWN


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def p0_compatible(me1, me2):
    """Coarser print must be the nearest-rounding of the finer (interval
    containment at the coarser step); equal precision requires equality."""
    if me1 is None or me2 is None:
        return False
    fine, coarse = (me1, me2) if me1.ulp <= me2.ulp else (me2, me1)
    if fine.ulp == coarse.ulp:
        return fine.center == coarse.center
    return abs(fine.center - coarse.center) * 2 <= coarse.ulp


def score(entry1, entry2, m1, mr, sib, nb):
    verdicts = []
    for key in ROWS:
        a, z = key
        rowid = f"{a}_{z}"
        out = r3.local_checks(m1, mr, key)
        me1, me2 = m1[key]["me"], mr[key]["me"]
        compatible = p0_compatible(me1, me2)
        out["P0_compatible"] = compatible
        out["me_mass1"] = str(me1.center)
        out["me_massround"] = str(me2.center)
        if not compatible:
            out["verdict"] = "SPECIAL"
            out["special_reason"] = "editions print incompatible mass excesses"
            verdicts.append(out)
            continue  # C656: no verdict branch beyond this point
        am1, am2 = m1[key]["am"], mr[key]["am"]
        e1, e2 = entry1.get(rowid), entry2.get(rowid)
        v1v, journal_value = "NO_VOTE", None
        if e1 and e2 and e1.get("am_microu") and e1.get("am_microu") == e2.get("am_microu"):
            journal_value = Fraction(e1["am_microu"])
            v1v = ("FIDELITY_OK" if journal_value == am2.center else
                   "J_MISMATCH_SIDES_MASS1" if journal_value == am1.center else "J_OTHER")
        elif e1 and e2:
            v1v = "DOUBLE_ENTRY_DISAGREE"
        out["V1"] = {"vote": v1v,
                     "journal_am": str(journal_value) if journal_value is not None else None,
                     "entry1": e1, "entry2": e2}
        sam = sib[key]["am"]
        v2v = ("SIBLING_OK" if sam.center == am1.center else
               "S_MISMATCH_SIDES_MASSROUND" if sam.center == am2.center else "S_OTHER")
        out["V2"] = {"vote": v2v, "sibling_am": str(sam.center)}
        nme = nb.get(key, {}).get("me")
        if nme is None:
            v3v = "N_ABSENT"
        else:
            lo1, hi1 = me1.center - me1.ulp / 2, me1.center + me1.ulp / 2
            lo2, hi2 = nme.center - nme.ulp / 2, nme.center + nme.ulp / 2
            v3v = "N_CONSISTENT" if not (hi1 < lo2 or hi2 < lo1) else "N_MISMATCH"
        out["V3"] = {"vote": v3v, "nubase_me": str(nme.center) if nme else None}
        # descriptive separable-row leaning (D2 authority: descriptive only)
        implied = Fraction(a) * 1_000_000 + me1.center * 1_000_000 / K
        e = (me1.ulp / 2) * 1_000_000 / K
        da, db = abs(implied - am1.center), abs(implied - am2.center)
        if abs(da - db) > 2 * e:
            out["separable_leaning_descriptive"] = {
                "leans_to": "mass_1" if da < db else "massround",
                "margin_microu": str(float(abs(da - db) - 2 * e))}
        if v1v == "J_MISMATCH_SIDES_MASS1":
            verdict = "SLIP_MASSROUND"
        elif v2v == "S_MISMATCH_SIDES_MASSROUND":
            verdict = "SLIP_MASS1"
        elif (v1v == "FIDELITY_OK" and v2v == "SIBLING_OK"
              and out["D1"]["mass_1_one_ulp_coherent"]
              and out["D1"]["massround_one_ulp_coherent"]):
            verdict = "TIE_NOT_EXCLUDED"
        else:
            verdict = "UNCLEAR"
        out["verdict"] = verdict
        verdicts.append(out)
    return verdicts


def controls(m1, mr, sib, nb):
    rep = {}
    joins = {}
    ok = True
    for key in KNOWN:
        joins[str(key)] = {"mass_1": key in m1, "massround": key in mr,
                           "sibling": key in sib, "nubase": key in nb}
        ok &= all(joins[str(key)].values())
    rep["known_answer_join"] = {"joins": joins, "passed": ok}

    key = ROWS[0]
    am1c, am2c = str(m1[key]["am"].center), str(mr[key]["am"].center)
    full = {f"{a}_{z}": None for a, z in ROWS}
    def entry(v): return {**full, f"{key[0]}_{key[1]}": {"am_microu": v, "page": 0}}
    planted = {}
    vs = score(entry(am1c), entry(am1c), m1, mr, sib, nb)
    planted["slip_massround"] = vs[0]["verdict"] == "SLIP_MASSROUND"
    vs = score(entry(am2c), entry(am2c), m1, mr, sib, nb)
    planted["fidelity_path"] = vs[0]["verdict"] in ("TIE_NOT_EXCLUDED", "UNCLEAR", "SLIP_MASS1")
    vs = score(entry(am1c), entry(am2c), m1, mr, sib, nb)
    planted["double_entry_disagree"] = vs[0]["verdict"] in ("UNCLEAR", "SLIP_MASS1")
    # planted P0 violation: mutate massround's ME to an incompatible value
    mut = {k: (dict(v) if k == key else v) for k, v in mr.items()}
    old = mut[key]["me"]
    mut[key]["me"] = r3.v1.Val(old.center + Fraction(1), old.ulp, old.cls)
    vs = score(entry(am2c), entry(am2c), m1, mut, sib, nb)
    planted["p0_violation_special"] = vs[0]["verdict"] == "SPECIAL"
    # finer-vs-coarser compatible pair must PASS P0 (real 88Sr row)
    vs_all = score(full, full, m1, mr, sib, nb)
    sr = next(v for v in vs_all if (v["a"], v["z"]) == (88, 38))
    planted["fine_coarse_compatible_passes_p0"] = bool(sr["P0_compatible"])
    rep["planted"] = {**planted, "passed": all(planted.values())}

    # deletion: bypassing the P0 gate must flip the planted SPECIAL control
    def score_no_p0(e1, e2, m1x, mrx):
        import types
        real = p0_compatible
        try:
            globals()["p0_compatible"] = lambda a, b: True
            return score(e1, e2, m1x, mrx, sib, nb)
        finally:
            globals()["p0_compatible"] = real
    vs = score_no_p0(entry(am2c), entry(am2c), m1, mut)
    rep["deletion"] = {"p0_gate_removed_verdict": vs[0]["verdict"],
                      "passed": vs[0]["verdict"] != "SPECIAL"}
    rep["passed"] = all(rep[k]["passed"] for k in ("known_answer_join", "planted", "deletion"))
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["controls", "score"], required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    r3.check_pins()
    def _blocked(*_a, **_k):
        raise RuntimeError("network banned in scoring")
    socket.socket = _blocked  # type: ignore[assignment]
    m1, mr, sib, nb = r3.load_editions()
    my_hash = sha256_file(Path(__file__))
    if args.mode == "controls":
        payload = {"schema": "aletheia.r3-edition-check.controls.v2",
                   "verifier_sha256": my_hash,
                   "report": controls(m1, mr, sib, nb)}
    else:
        entry1 = json.loads((ROUTE / "EXTRACTION_ENTRY_1.json").read_text())
        entry2 = json.loads((ROUTE / "EXTRACTION_ENTRY_2.json").read_text())
        payload = {"schema": "aletheia.r3-edition-check.score.v2",
                   "verifier_sha256": my_hash,
                   "entry1_sha256": sha256_file(ROUTE / "EXTRACTION_ENTRY_1.json"),
                   "entry2_sha256": sha256_file(ROUTE / "EXTRACTION_ENTRY_2.json"),
                   "verdicts": score(entry1, entry2, m1, mr, sib, nb)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    ok = payload.get("report", {}).get("passed", True)
    print(json.dumps({"mode": args.mode, "passed": ok, "out": str(args.out)}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
