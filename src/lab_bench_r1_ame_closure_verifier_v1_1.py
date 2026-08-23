#!/usr/bin/env python3
"""R1_AME_CLOSURE verifier v1.1 — post-review accounting and control repair.

Changes vs v1 (per Codex A10 review 2026-08-22 and Catch C632):
- Census accounting: every family reports missing_printed, missing_dependency,
  and per-class (EXP/EST) eligible counts; nothing is silently skipped.
- Planted controls: one mutation per relation family (A, B, C, D, E, F, G),
  each bound to its intended family, column, row, and sign; a nearby flag from
  another family cannot satisfy a control.
- Deletion controls: per-family, using that family's own planted mutation,
  requiring at least one positive detection before deletion can pass; G included.
- Clean fixture: a synthetic self-consistent multi-family fixture with literal
  '#', '*', and missing-neighbor quirks, run through families A-G.
Verdict logic (interval envelopes, disjointness, relation formulas, parsers)
is UNCHANGED from v1; v1 receipts (CENSUS_V1) remain the frozen outcome record,
independently reproduced by the Codex review. This version regenerates the
census with honest denominators as CENSUS_V2.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from fractions import Fraction
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "r1_v1", "/data/adp/scripts/lab_bench_r1_ame_closure_verifier_v1.py")
v1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v1)

Val = v1.Val
interval = v1.interval
combine = v1.combine
disjoint = v1.disjoint
flag_record = v1.flag_record
RCT_COLS = v1.RCT_COLS
RCT_DEFS = v1.RCT_DEFS
KEV_PER_U = v1.KEV_PER_U


def _cls_count(census: dict, val: Val) -> None:
    census[val.cls] = census.get(val.cls, 0) + 1


def relation_A(mass, h, disable=frozenset()):
    flags, census = [], {"eligible": 0, "missing_printed": 0, "missing_dependency": 0}
    for key, r in sorted(mass.items()):
        if r["me"] is None or r["am"] is None:
            census["missing_printed"] += 1
            continue
        census["eligible"] += 1
        _cls_count(census, r["me"])
        lo, hi = combine([(KEV_PER_U / 1_000_000, r["am"])], h)
        a_kev = Fraction(r["a"]) * KEV_PER_U
        lo, hi = lo - a_kev, hi - a_kev
        if "A" not in disable and disjoint((lo, hi), interval(r["me"], h)):
            flags.append(flag_record("A_me_vs_am", key, r["me"], lo, hi, r, h))
    return flags, census


def relation_B(mass, h, disable=frozenset()):
    flags, census = [], {"eligible": 0, "missing_printed": 0, "missing_dependency": 0}
    for key, r in sorted(mass.items()):
        if r["beta"] is None or r["bflag"] != "B-":
            census["missing_printed"] += 1
            continue
        dest = mass.get((r["a"], r["z"] + 1))
        if dest is None or dest["me"] is None or r["me"] is None:
            census["missing_dependency"] += 1
            continue
        census["eligible"] += 1
        _cls_count(census, r["beta"])
        lo, hi = combine([(Fraction(1), r["me"]), (Fraction(-1), dest["me"])], h)
        if "B" not in disable and disjoint((lo, hi), interval(r["beta"], h)):
            flags.append(flag_record("B_beta", key, r["beta"], lo, hi, r, h))
    return flags, census


def relation_C(mass, h, disable=frozenset()):
    flags, census = [], {"eligible": 0, "missing_printed": 0, "missing_dependency": 0}
    me_h, me_n = mass[(1, 1)]["me"], mass[(1, 0)]["me"]
    for key, r in sorted(mass.items()):
        if r["be"] is None or r["a"] == 0:
            census["missing_printed"] += 1
            continue
        if r["me"] is None:
            census["missing_dependency"] += 1
            continue
        census["eligible"] += 1
        _cls_count(census, r["be"])
        lo, hi = combine([(Fraction(r["z"]), me_h), (Fraction(r["n"]), me_n),
                          (Fraction(-1), r["me"])], h)
        lo, hi = lo / r["a"], hi / r["a"]
        if "C" not in disable and disjoint((lo, hi), interval(r["be"], h)):
            flags.append(flag_record("C_be_per_a", key, r["be"], lo, hi, r, h))
    return flags, census


def relation_DE(mass, rct, which, h, disable=frozenset()):
    flags = []
    fam = "D" if which == "rct1" else "E"
    census = {c: {"eligible": 0, "missing_printed": 0, "missing_dependency": 0}
              for c in RCT_COLS[which]}
    for key, r in sorted(rct.items()):
        a, z = key
        for col in RCT_COLS[which]:
            printed = r[col]
            if printed is None:
                census[col]["missing_printed"] += 1
                continue
            terms = []
            ok = True
            for coef, mkey in RCT_DEFS[col](a, z):
                m = mass.get(mkey)
                if m is None or m["me"] is None:
                    ok = False
                    break
                terms.append((Fraction(coef), m["me"]))
            if not ok:
                census[col]["missing_dependency"] += 1
                continue
            census[col]["eligible"] += 1
            _cls_count(census[col], printed)
            lo, hi = combine(terms, h)
            if fam not in disable and disjoint((lo, hi), interval(printed, h)):
                flags.append(flag_record(f"{fam}_{col}", key, printed, lo, hi, r, h))
    return flags, census


def relation_F(rct1, rct2, h, disable=frozenset()):
    flags = []
    census = {"s2n_chain": {"eligible": 0, "missing_printed": 0, "missing_dependency": 0},
              "s2p_chain": {"eligible": 0, "missing_printed": 0, "missing_dependency": 0}}
    for (a, z), r in sorted(rct1.items()):
        for col, chain in (("s2n", [((a, z), "sn"), ((a - 1, z), "sn")]),
                           ("s2p", [((a, z), "sp"), ((a - 1, z - 1), "sp")])):
            printed = r[col]
            ckey = col + "_chain"
            if printed is None:
                census[ckey]["missing_printed"] += 1
                continue
            terms = []
            ok = True
            for key2, c2 in chain:
                r2 = rct2.get(key2)
                if r2 is None or r2[c2] is None:
                    ok = False
                    break
                terms.append((Fraction(1), r2[c2]))
            if not ok:
                census[ckey]["missing_dependency"] += 1
                continue
            census[ckey]["eligible"] += 1
            _cls_count(census[ckey], printed)
            lo, hi = combine(terms, h)
            if "F" not in disable and disjoint((lo, hi), interval(printed, h)):
                flags.append(flag_record(f"F_{col}_chain", (a, z), printed, lo, hi, r, h))
    return flags, census


relation_G = v1.relation_G  # unchanged; frozen-rule G stays VOID per REPORT.md


def run_all(mass, rct1, rct2, rounded, h, disable=frozenset()):
    return {
        "A": relation_A(mass, h, disable),
        "B": relation_B(mass, h, disable),
        "C": relation_C(mass, h, disable),
        "D": relation_DE(mass, rct1, "rct1", h, disable),
        "E": relation_DE(mass, rct2, "rct2", h, disable),
        "F": relation_F(rct1, rct2, h, disable),
        "G": relation_G(mass, rounded, disable),
    }


def _mut_mass(mass, key, col, delta):
    m2 = {k: (dict(v) if k == key else v) for k, v in mass.items()}
    old = m2[key][col]
    m2[key][col] = Val(old.center + delta, old.ulp, old.cls)
    return m2


def _mut_rct(rct, key, col, delta):
    r2 = {k: (dict(v) if k == key else v) for k, v in rct.items()}
    old = r2[key][col]
    r2[key][col] = Val(old.center + delta, old.ulp, old.cls)
    return r2


def controls(mass, rct1, rct2, rounded) -> dict:
    half = Fraction(1, 2)
    report = {}

    # known answers (unchanged from v1)
    assert mass[(1, 0)]["me"].center == Fraction("8071.31806")
    assert mass[(1, 0)]["am"].center == Fraction("1008664.91590")
    assert rct2[(2, 1)]["sn"].center == Fraction("2224.5662")
    base = run_all(mass, rct1, rct2, rounded, half)
    ka = [f for rel in "ABCDEF" for f in base[rel][0] if (f["a"], f["z"]) in v1.KNOWN]
    report["known_answer"] = {"flags_in_known_set": len(ka), "passed": not ka}

    # bound planted controls: (name, family, expected relation prefix, builder)
    baseline_g = len(base["G"][0])
    plans = [
        ("A_up_small", "A", "A_me_vs_am", (56, 26),
         lambda: (_mut_mass(mass, (56, 26), "me", Fraction(1, 200)), rct1, rct2, rounded)),
        ("A_down_small", "A", "A_me_vs_am", (56, 26),
         lambda: (_mut_mass(mass, (56, 26), "me", Fraction(-1, 200)), rct1, rct2, rounded)),
        ("B_beta_up", "B", "B_beta", (56, 25),
         lambda: (_mut_mass(mass, (56, 25), "beta", Fraction(1)), rct1, rct2, rounded)),
        ("C_be_down", "C", "C_be_per_a", (16, 8),
         lambda: (_mut_mass(mass, (16, 8), "be", Fraction(-1, 5000)), rct1, rct2, rounded)),
        ("D_s2n_up", "D", "D_s2n", (18, 8),
         lambda: (mass, _mut_rct(rct1, (18, 8), "s2n", Fraction(3, 1000)), rct2, rounded)),
        ("E_sn_up", "E", "E_sn", (2, 1),
         lambda: (mass, rct1, _mut_rct(rct2, (2, 1), "sn", Fraction(1, 5000)), rounded)),
        ("F_chain_sn", "F", "F_s2n_chain", (18, 8),
         lambda: (mass, rct1, _mut_rct(rct2, (18, 8), "sn", Fraction(3, 1000)), rounded)),
        ("G_round_shift", "G", "G_round", (1, 0),
         lambda: (mass, rct1, rct2, _mut_rounded(rounded, (1, 0), Fraction(1, 10)))),
    ]

    def _mut_rounded(rnd, key, delta):
        r2 = {k: (dict(v) if k == key else v) for k, v in rnd.items()}
        old = r2[key]["me"]
        r2[key]["me"] = Val(old.center + delta, old.ulp, old.cls)
        return r2

    planted = {}
    all_ok = True
    fam_mut = {}
    for name, fam, relpfx, key, build in plans:
        m2, r12, r22, rnd2 = build()
        res = run_all(m2, r12, r22, rnd2, half)
        if fam == "G":
            hit = len(res["G"][0]) == baseline_g + 1 and any(
                (f["a"], f["z"]) == key for f in res["G"][0])
        else:
            hit = any(f["relation"].startswith(relpfx) and (f["a"], f["z"]) == key
                      for f in res[fam][0])
        planted[name] = {"family": fam, "bound_relation": relpfx, "row": list(key),
                         "caught_in_bound_family": hit}
        fam_mut.setdefault(fam, (name, key, relpfx, (m2, r12, r22, rnd2), hit))
        all_ok &= hit
    planted["passed"] = all_ok
    report["planted"] = planted

    # per-family deletion using that family's own planted mutation; requires a
    # positive detection first (C632).
    deletion = {}
    del_ok = True
    for fam, (name, key, relpfx, tables, hit) in fam_mut.items():
        m2, r12, r22, rnd2 = tables
        off = run_all(m2, r12, r22, rnd2, half, disable=frozenset(fam))
        if fam == "G":
            still = any((f["a"], f["z"]) == key for f in off["G"][0])
        else:
            still = any(f["relation"].startswith(relpfx) and (f["a"], f["z"]) == key
                        for f in off[fam][0])
        ok = hit and not still
        deletion[fam] = {"planted": name, "detected_enabled": hit,
                         "detected_disabled": still, "passed": ok}
        del_ok &= ok
    deletion["passed"] = del_ok
    report["deletion"] = deletion

    # synthetic clean fixture across families with '#', '*', missing-neighbor
    fx_mass, fx_r1, fx_r2, fx_round = _fixture()
    fres = run_all(fx_mass, fx_r1, fx_r2, fx_round, half)
    fx_flags = sum(len(fres[rel][0]) for rel in "ABCDEF") + len(fres["G"][0])
    fx_census = {rel: fres[rel][1] for rel in "ABCDEFG"}
    quirks_seen = (fx_census["A"].get("EST", 0) >= 1
                   and fx_census["B"]["missing_dependency"] >= 1
                   and fx_census["E"]["sn"]["missing_printed"] >= 1)
    report["clean_fixture"] = {"flags": fx_flags, "quirks_exercised": quirks_seen,
                               "passed": fx_flags == 0 and quirks_seen}

    report["passed"] = all(report[k]["passed"] for k in
                           ("known_answer", "planted", "deletion", "clean_fixture"))
    return report


def _fixture():
    """Self-consistent synthetic tables: MEs chosen exactly, derived columns
    computed exactly, plus '#' (EST), '*' (missing), and missing-neighbor rows."""
    def val(s, cls="EXP"):
        c = Fraction(s)
        dec = len(s.split(".")[1]) if "." in s else 0
        return Val(c, Fraction(1, 10 ** dec), cls)

    me = {(1, 0): val("8000.00000"), (1, 1): val("7000.00000"),
          (2, 1): val("13000.00000"), (3, 1): val("15000.00000"),
          (3, 2): val("14900.00000"), (4, 2): val("2400.00000", "EST")}
    mass = {}
    for (a, z), m in me.items():
        n = a - z
        am = Val(Fraction(a) * 1_000_000 + m.center * 1_000_000 / KEV_PER_U,
                 Fraction(1, 10 ** 5), m.cls)
        # BE/A from the fixture's own MEs
        be = None
        if a > 0:
            bec = (Fraction(z) * me[(1, 1)].center + Fraction(n) * me[(1, 0)].center
                   - m.center) / a
            be = Val(bec, Fraction(1, 10 ** 4), "EXP")
        beta = None
        bflag = ""
        if (a, z + 1) in me:
            beta = Val(m.center - me[(a, z + 1)].center, Fraction(1, 10 ** 4), "EXP")
            bflag = "B-"
        mass[(a, z)] = {"n": n, "z": z, "a": a, "el": "fx", "me": m, "am": am,
                        "be": be, "beta": beta, "bflag": bflag, "lineno": 0,
                        "raw": "fixture", "raw_sha256": "0" * 64}
    # missing-neighbor row: beta printed but neighbor absent
    mass[(5, 2)] = {"n": 3, "z": 2, "a": 5, "el": "fx",
                    "me": val("20000.00000"), "am": None,
                    "be": None, "beta": val("1.0000"), "bflag": "B-",
                    "lineno": 0, "raw": "fixture", "raw_sha256": "0" * 64}
    r1 = {}
    r2 = {}
    for (a, z) in me:
        row1 = {"lineno": 0, "raw": "fixture", "raw_sha256": "0" * 64}
        row2 = dict(row1)
        for col in RCT_COLS["rct1"]:
            row1[col] = None
            row1[col + "_u"] = None
        for col in RCT_COLS["rct2"]:
            row2[col] = None
            row2[col + "_u"] = None
        # exact S(2n) and S(n)/S(p) where dependencies exist
        if (a - 2, z) in me:
            c = -me[(a, z)].center + me[(a - 2, z)].center + 2 * me[(1, 0)].center
            row1["s2n"] = Val(c, Fraction(1, 10 ** 4), "EXP")
        if (a - 1, z) in me:
            c = -me[(a, z)].center + me[(a - 1, z)].center + me[(1, 0)].center
            row2["sn"] = Val(c, Fraction(1, 10 ** 4), "EXP")
        if (a - 1, z - 1) in me:
            c = -me[(a, z)].center + me[(a - 1, z - 1)].center + me[(1, 1)].center
            row2["sp"] = Val(c, Fraction(1, 10 ** 4), "EXP")
        r1[(a, z)] = row1
        r2[(a, z)] = row2
    # '*' quirk: 3H S(n) deliberately missing although computable
    r2[(3, 1)]["sn"] = None
    rounded = {}
    for (a, z), r in mass.items():
        if r["me"] is None or r["me"].cls != "EXP":
            continue
        step = Fraction(1, 100)
        q = r["me"].center / step
        fl = q.numerator // q.denominator
        near = fl * step if (r["me"].center - fl * step) * 2 <= step else (fl + 1) * step
        rounded[(a, z)] = {"n": r["n"], "z": z, "a": a, "el": "fx",
                           "me": Val(near, step, "EXP"), "am": None, "be": None,
                           "beta": None, "bflag": "", "lineno": 0,
                           "raw": "fixture", "raw_sha256": "0" * 64}
    return mass, r1, r2, rounded


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["controls", "census"], required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    v1.assert_no_llm()
    mass, rct1, rct2, rounded = v1.load_frozen()
    if args.mode == "controls":
        payload = {"schema": "aletheia.r1-ame-closure.controls.v1_1",
                   "verifier_sha256": v1.sha256(Path(__file__)),
                   "report": controls(mass, rct1, rct2, rounded)}
    else:
        results = {}
        for label, h in (("half_ulp", Fraction(1, 2)), ("one_ulp", Fraction(1))):
            res = run_all(mass, rct1, rct2, rounded, h)
            results[label] = {rel: {"flags": res[rel][0], "census": res[rel][1]}
                              for rel in "ABCDEFG"}
        payload = {"schema": "aletheia.r1-ame-closure.census.v1_1",
                   "note": "accounting repair per Codex A10 review and C632; verdict logic identical to v1 (CENSUS_V1 remains the frozen outcome record)",
                   "verifier_sha256": v1.sha256(Path(__file__)),
                   "row_counts": {"mass": len(mass), "rct1": len(rct1),
                                  "rct2": len(rct2), "round": len(rounded)},
                   "results": results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    ok = payload.get("report", {}).get("passed", True)
    print(json.dumps({"mode": args.mode, "passed": ok, "out": str(args.out)}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
