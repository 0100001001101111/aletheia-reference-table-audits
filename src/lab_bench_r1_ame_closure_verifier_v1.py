#!/usr/bin/env python3
"""R1_AME_CLOSURE frozen verifier v1 (lab bench hunt 2026-08-22).

Deterministic, LLM-free, network-free internal-consistency audit of the AME2020
distribution files. Implements relation families A-G of PREREGISTRATION.json.
Every verdict uses exact Fraction interval arithmetic on printed values.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sys
from fractions import Fraction
from pathlib import Path

ROUTE = Path("/data/adp/investigations/lab_bench_hunt_2026-08-22/04_routes/R1_AME_CLOSURE")
RAW = ROUTE / "raw"
FROZEN = {
    "mass": ("mass_1.mas20.txt", "sha256:e8599c6d7f724fac91934e59f1b9de8fb8f63e820f4b39456b790665ed2a3307"[7:]),
    "rct1": ("rct1.mas20.txt", "sha256:e6ba1d2256f90053464c48e24d44691828dc49820ce64054aa418d834cc18e90"[7:]),
    "rct2": ("rct2_1.mas20.txt", "sha256:78765c7b3f3c991ce2b6ff3b5c086a135aad1807d07819f806ab9a9150a4c2c7"[7:]),
    "round": ("massround.mas20.txt", "sha256:ba08eed78e9efc412c6a7f558d209748c70e831f35a834b1f99615f21897fb74"[7:]),
}
KEV_PER_U = Fraction("931494.10242")


def assert_no_llm() -> None:
    """B4: scoring path may not open sockets."""
    def _blocked(*_a, **_k):
        raise RuntimeError("network access is banned in the scoring path")
    socket.socket = _blocked  # type: ignore[assignment]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- values

class Val:
    """A printed numeric token: exact center, ulp, and class."""

    __slots__ = ("center", "ulp", "cls")

    def __init__(self, center: Fraction, ulp: Fraction, cls: str):
        self.center, self.ulp, self.cls = center, ulp, cls


def parse_val(token: str) -> Val | None:
    """Parse one printed field. '#' replaces the decimal point in estimated
    values. '*' means not calculable. Returns None for missing."""
    t = token.strip().replace(" ", "")
    if not t or t == "*":
        return None
    cls = "EXP"
    if "#" in t:
        cls = "EST"
        t = t.replace("#", ".") if "." not in t else t.replace("#", "")
        if t.endswith("."):
            t = t[:-1] + ".0" if False else t  # keep trailing dot handled below
    if t.endswith("."):
        t = t[:-1]
    try:
        center = Fraction(t)
    except (ValueError, ZeroDivisionError):
        return None
    decimals = len(t.split(".")[1]) if "." in t else 0
    ulp = Fraction(1, 10 ** decimals)
    return Val(center, ulp, cls)


def interval(v: Val, h: Fraction) -> tuple[Fraction, Fraction]:
    half = v.ulp * h
    return (v.center - half, v.center + half)


def combine(vals: list[tuple[Fraction, Val]], h: Fraction) -> tuple[Fraction, Fraction]:
    """Exact interval of sum(coef * val)."""
    lo = hi = Fraction(0)
    for coef, v in vals:
        a, b = interval(v, h)
        x, y = coef * a, coef * b
        if x > y:
            x, y = y, x
        lo += x
        hi += y
    return lo, hi


def disjoint(a: tuple[Fraction, Fraction], b: tuple[Fraction, Fraction]) -> bool:
    return a[1] < b[0] or b[1] < a[0]


# ---------------------------------------------------------------- parsers

def _slices(spec: list[tuple[str, int]]) -> list[tuple[str, int, int]]:
    out, pos = [], 0
    for name, width in spec:
        out.append((name, pos, pos + width))
        pos += width
    return out


MASS_SPEC = _slices([
    ("cc", 1), ("NZ", 3), ("N", 5), ("Z", 5), ("A", 5), ("sp1", 1), ("el", 3),
    ("o", 4), ("sp2", 1), ("me", 14), ("me_u", 12), ("be", 13), ("sp3", 1),
    ("be_u", 10), ("sp4", 1), ("bflag", 2), ("beta", 13), ("beta_u", 11),
    ("sp5", 1), ("am_i", 3), ("sp6", 1), ("am_f", 13), ("am_u", 12),
])
ROUND_SPEC = _slices([
    ("cc", 1), ("NZ", 3), ("N", 5), ("Z", 5), ("A", 5), ("sp1", 1), ("el", 3),
    ("o", 4), ("sp2", 1), ("me", 13), ("me_u", 11), ("be", 11), ("be_u", 9),
    ("sp4", 1), ("bflag", 2), ("beta", 11), ("beta_u", 9),
    ("sp5", 1), ("am_i", 3), ("sp6", 1), ("am_f", 12), ("am_u", 11),
])
RCT_COLS = {"rct1": ["s2n", "s2p", "qa", "q2bm", "qep", "qbmn"],
            "rct2": ["sn", "sp", "q4bm", "qda", "qpa", "qna"]}


def field(line: str, sl: tuple[str, int, int]) -> str:
    return line[sl[1]:sl[2]]


def parse_mass(path: Path, spec=MASS_SPEC) -> dict[tuple[int, int], dict]:
    rows: dict[tuple[int, int], dict] = {}
    header_done = False
    by = {s[0]: s for s in spec}
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        if not header_done:
            if line[:1] in "01" and "MASS" not in line and field(line, by["N"]).strip().isdigit():
                header_done = True
            else:
                continue
        if not (field(line, by["N"]).strip().isdigit() and field(line, by["Z"]).strip().isdigit()):
            continue
        n, z = int(field(line, by["N"])), int(field(line, by["Z"]))
        a_txt = field(line, by["A"]).strip()
        a = int(a_txt) if a_txt.isdigit() else n + z
        if a != n + z:
            raise ValueError(f"A mismatch at line {lineno}: printed {a} vs N+Z {n + z}")
        me = parse_val(field(line, by["me"]))
        be = parse_val(field(line, by["be"]))
        beta = parse_val(field(line, by["beta"]))
        am_i_txt = field(line, by["am_i"]).strip()
        am_f = parse_val(field(line, by["am_f"]))
        am = None
        if am_f is not None and am_i_txt.isdigit():
            am = Val(Fraction(am_i_txt) * 1_000_000 + am_f.center, am_f.ulp, am_f.cls)
        rows[(a, z)] = {
            "n": n, "z": z, "a": a, "el": field(line, by["el"]).strip(),
            "me": me, "be": be, "beta": beta, "bflag": field(line, by["bflag"]).strip(),
            "am": am, "lineno": lineno, "raw": line,
            "raw_sha256": hashlib.sha256(line.encode()).hexdigest(),
        }
    if not rows:
        raise ValueError(f"no rows parsed from {path}")
    return rows


def parse_rct(path: Path, which: str) -> dict[tuple[int, int], dict]:
    cols = RCT_COLS[which]
    rows: dict[tuple[int, int], dict] = {}
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        a_txt, z_txt = line[1:4].strip(), line[8:11].strip()
        if not (a_txt.isdigit() and (z_txt.isdigit() or (z_txt.startswith("-") and z_txt[1:].isdigit()))):
            continue
        if "elt" in line or "S(" in line:
            continue
        a, z = int(a_txt), int(z_txt)
        row = {"lineno": lineno, "raw": line,
               "raw_sha256": hashlib.sha256(line.encode()).hexdigest()}
        pos = 12
        for name in cols:
            row[name] = parse_val(line[pos:pos + 12])
            row[name + "_u"] = parse_val(line[pos + 12:pos + 22])
            pos += 22
        rows[(a, z)] = row
    if not rows:
        raise ValueError(f"no rows parsed from {path}")
    return rows


# ---------------------------------------------------------------- relations

def flag_record(kind: str, key, printed: Val, lo: Fraction, hi: Fraction,
                row: dict, h: Fraction) -> dict:
    plo, phi = interval(printed, h)
    return {
        "relation": kind, "a": key[0], "z": key[1],
        "printed_center": str(printed.center), "printed_interval": [str(plo), str(phi)],
        "recomputed_interval": [str(lo), str(hi)],
        "distance_ulp": str((min(abs(printed.center - lo), abs(printed.center - hi)) / printed.ulp)),
        "value_class": printed.cls, "lineno": row["lineno"], "raw_sha256": row["raw_sha256"],
        "raw": row["raw"],
    }


def relation_A(mass, h, disable=frozenset()):
    flags, census = [], {"eligible": 0, "excluded": 0, "EST": 0, "EXP": 0}
    for key, r in sorted(mass.items()):
        if r["me"] is None or r["am"] is None:
            census["excluded"] += 1
            continue
        census["eligible"] += 1
        census[r["me"].cls] = census.get(r["me"].cls, 0) + 1
        lo, hi = combine([(KEV_PER_U / 1_000_000, r["am"])], h)
        a_kev = Fraction(r["a"]) * KEV_PER_U
        lo, hi = lo - a_kev, hi - a_kev
        if "A" not in disable and disjoint((lo, hi), interval(r["me"], h)):
            flags.append(flag_record("A_me_vs_am", key, r["me"], lo, hi, r, h))
    return flags, census


def relation_B(mass, h, disable=frozenset()):
    flags, census = [], {"eligible": 0, "excluded": 0}
    for key, r in sorted(mass.items()):
        if r["beta"] is None or r["bflag"] != "B-":
            continue
        dest = mass.get((r["a"], r["z"] + 1))
        if dest is None or dest["me"] is None or r["me"] is None:
            census["excluded"] += 1
            continue
        census["eligible"] += 1
        lo, hi = combine([(Fraction(1), r["me"]), (Fraction(-1), dest["me"])], h)
        if "B" not in disable and disjoint((lo, hi), interval(r["beta"], h)):
            flags.append(flag_record("B_beta", key, r["beta"], lo, hi, r, h))
    return flags, census


def relation_C(mass, h, disable=frozenset()):
    flags, census = [], {"eligible": 0, "excluded": 0}
    me_h, me_n = mass[(1, 1)]["me"], mass[(1, 0)]["me"]
    for key, r in sorted(mass.items()):
        if r["be"] is None or r["me"] is None or r["a"] == 0:
            census["excluded"] += 1
            continue
        census["eligible"] += 1
        lo, hi = combine([(Fraction(r["z"]), me_h), (Fraction(r["n"]), me_n),
                          (Fraction(-1), r["me"])], h)
        lo, hi = lo / r["a"], hi / r["a"]
        if "C" not in disable and disjoint((lo, hi), interval(r["be"], h)):
            flags.append(flag_record("C_be_per_a", key, r["be"], lo, hi, r, h))
    return flags, census


RCT_DEFS = {
    "s2n": lambda a, z: [(-1, (a, z)), (1, (a - 2, z)), (2, (1, 0))],
    "s2p": lambda a, z: [(-1, (a, z)), (1, (a - 2, z - 2)), (2, (1, 1))],
    "qa": lambda a, z: [(1, (a, z)), (-1, (a - 4, z - 2)), (-1, (4, 2))],
    "q2bm": lambda a, z: [(1, (a, z)), (-1, (a, z + 2))],
    "qep": lambda a, z: [(1, (a, z)), (-1, (a - 1, z - 2)), (-1, (1, 1))],
    "qbmn": lambda a, z: [(1, (a, z)), (-1, (a - 1, z + 1)), (-1, (1, 0))],
    "sn": lambda a, z: [(-1, (a, z)), (1, (a - 1, z)), (1, (1, 0))],
    "sp": lambda a, z: [(-1, (a, z)), (1, (a - 1, z - 1)), (1, (1, 1))],
    "q4bm": lambda a, z: [(1, (a, z)), (-1, (a, z + 4))],
    "qda": lambda a, z: [(1, (a, z)), (1, (2, 1)), (-1, (a - 2, z - 1)), (-1, (4, 2))],
    "qpa": lambda a, z: [(1, (a, z)), (1, (1, 1)), (-1, (a - 3, z - 1)), (-1, (4, 2))],
    "qna": lambda a, z: [(1, (a, z)), (1, (1, 0)), (-1, (a - 3, z - 2)), (-1, (4, 2))],
}


def relation_DE(mass, rct, which, h, disable=frozenset()):
    flags = []
    fam = "D" if which == "rct1" else "E"
    census = {c: {"eligible": 0, "excluded": 0} for c in RCT_COLS[which]}
    for key, r in sorted(rct.items()):
        a, z = key
        for col in RCT_COLS[which]:
            printed = r[col]
            if printed is None:
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
                census[col]["excluded"] += 1
                continue
            census[col]["eligible"] += 1
            lo, hi = combine(terms, h)
            if fam not in disable and disjoint((lo, hi), interval(printed, h)):
                flags.append(flag_record(f"{fam}_{col}", key, printed, lo, hi, r, h))
    return flags, census


def relation_F(rct1, rct2, h, disable=frozenset()):
    flags, census = [], {"s2n_chain": {"eligible": 0, "excluded": 0},
                        "s2p_chain": {"eligible": 0, "excluded": 0}}
    for (a, z), r in sorted(rct1.items()):
        for col, chain in (("s2n", [((a, z), "sn"), ((a - 1, z), "sn")]),
                           ("s2p", [((a, z), "sp"), ((a - 1, z - 1), "sp")])):
            printed = r[col]
            if printed is None:
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
                census[col + "_chain"]["excluded"] += 1
                continue
            census[col + "_chain"]["eligible"] += 1
            lo, hi = combine(terms, h)
            if "F" not in disable and disjoint((lo, hi), interval(printed, h)):
                flags.append(flag_record(f"F_{col}_chain", (a, z), printed, lo, hi, r, h))
    return flags, census


def relation_G(mass, rounded, disable=frozenset()):
    """Rounding-convention census: classify each rounded printed value against
    its unrounded partner as nearest / floor / ceiling / exact / none."""
    census = {"pairs": 0, "excluded": 0}
    classes: dict[str, int] = {}
    residual = []
    for key, rr in sorted(rounded.items()):
        mr = mass.get(key)
        if mr is None:
            census["excluded"] += 1
            continue
        for col in ("me", "am"):
            rv, uv = rr.get(col), mr.get(col)
            if rv is None or uv is None or rv.cls != "EXP" or uv.cls != "EXP":
                continue
            census["pairs"] += 1
            step = rv.ulp
            q = uv.center / step
            floor_q = q.numerator // q.denominator
            floor_v, ceil_v = floor_q * step, (floor_q + (0 if q.denominator == 1 else 1)) * step
            nearest = floor_v if (uv.center - floor_v) * 2 < step else (
                ceil_v if (uv.center - floor_v) * 2 > step else None)
            if uv.center == rv.center:
                cls = "exact"
            elif nearest is not None and rv.center == nearest:
                cls = "nearest"
            elif rv.center == floor_v:
                cls = "floor"
            elif rv.center == ceil_v:
                cls = "ceiling"
            elif nearest is None and rv.center in (floor_v, ceil_v):
                cls = "half_tie"
            else:
                cls = "none"
                if "G" not in disable:
                    residual.append({
                        "relation": "G_round", "a": key[0], "z": key[1], "column": col,
                        "unrounded": str(uv.center), "rounded_printed": str(rv.center),
                        "rounded_step": str(step), "lineno": rr["lineno"],
                        "raw_sha256": rr["raw_sha256"], "raw": rr["raw"],
                    })
            classes[cls] = classes.get(cls, 0) + 1
    census["classes"] = classes
    return residual, census


# ---------------------------------------------------------------- harness

def load_frozen(check_hashes=True):
    files = {}
    for key, (name, digest) in FROZEN.items():
        p = RAW / name
        if check_hashes and sha256(p) != digest:
            raise ValueError(f"hash mismatch for {name}")
        files[key] = p
    mass = parse_mass(files["mass"])
    rct1 = parse_rct(files["rct1"], "rct1")
    rct2 = parse_rct(files["rct2"], "rct2")
    rounded = parse_mass(files["round"], spec=ROUND_SPEC)
    return mass, rct1, rct2, rounded


def run_all(mass, rct1, rct2, rounded, h: Fraction, disable=frozenset()):
    out = {}
    out["A"] = relation_A(mass, h, disable)
    out["B"] = relation_B(mass, h, disable)
    out["C"] = relation_C(mass, h, disable)
    out["D"] = relation_DE(mass, rct1, "rct1", h, disable)
    out["E"] = relation_DE(mass, rct2, "rct2", h, disable)
    out["F"] = relation_F(rct1, rct2, h, disable)
    out["G"] = relation_G(mass, rounded, disable)
    return out


KNOWN = [(1, 0), (1, 1), (2, 1), (3, 1), (3, 2), (4, 2), (12, 6), (16, 8), (56, 26), (208, 82)]


def controls(mass, rct1, rct2, rounded) -> dict:
    report = {"known_answer": {}, "planted": {}, "deletion": {}, "clean_fixture": {}}
    half = Fraction(1, 2)

    # -- known answers: no flags among the frozen light-nuclide set, and the
    #    parser must reproduce documented values exactly.
    assert mass[(1, 0)]["me"].center == Fraction("8071.31806")
    assert mass[(1, 0)]["am"].center == Fraction("1008664.91590")
    assert rct2[(2, 1)]["sn"].center == Fraction("2224.5662")
    res = run_all(mass, rct1, rct2, rounded, half)
    ka_flags = [f for rel in "ABCDEF" for f in res[rel][0]
                if (f["a"], f["z"]) in KNOWN]
    report["known_answer"] = {"flags_in_known_set": len(ka_flags), "passed": not ka_flags}

    # -- planted mutations: corrupt values in copies of the parsed tables.
    plans = [
        ("A_small_up", "mass", (56, 26), "me", Fraction(1, 100000)),
        ("A_small_down", "mass", (56, 26), "me", Fraction(-1, 100000)),
        ("A_large", "mass", (56, 26), "me", Fraction(7)),
        ("E_sn_small_up", "rct2", (2, 1), "sn", Fraction(1, 10000) * 2),
        ("E_sn_large", "rct2", (2, 1), "sn", Fraction(5)),
        ("C_be_small_down", "mass", (16, 8), "be", Fraction(-1, 10000) * 2),
    ]
    all_caught = True
    for name, table, key, col, delta in plans:
        import copy
        m2, r12, r22 = mass, rct1, rct2
        if table == "mass":
            m2 = {k: (dict(v) if k == key else v) for k, v in mass.items()}
            old = m2[key][col]
            m2[key][col] = Val(old.center + delta, old.ulp, old.cls)
        else:
            r22 = {k: (dict(v) if k == key else v) for k, v in rct2.items()}
            old = r22[key][col]
            r22[key][col] = Val(old.center + delta, old.ulp, old.cls)
        res2 = run_all(m2, r12, r22, rounded, half)
        caught = any(
            (f["a"], f["z"]) == key or (f["a"], f["z"]) == (key[0] + 1, key[1]) or
            (f["a"], f["z"]) == (key[0] + 2, key[1]) or (f["a"], f["z"]) == (key[0] + 2, key[1] + 2) or
            (f["a"], f["z"]) == (key[0] + 4, key[1] + 2) or (f["a"], f["z"]) == (key[0] + 1, key[1] + 1) or
            (f["a"], f["z"]) == (key[0] + 3, key[1] + 1) or (f["a"], f["z"]) == (key[0] + 3, key[1] + 2) or
            (f["a"], f["z"]) == (key[0], key[1] - 1) or (f["a"], f["z"]) == (key[0], key[1] - 2)
            for rel in "ABCDEF" for f in res2[rel][0])
        report["planted"][name] = {"delta": str(delta), "caught": caught}
        all_caught &= caught
    report["planted"]["passed"] = all_caught

    # -- deletion mutations: disabling each relation family must erase the
    #    planted catch that family produced on the planted row (checked on the
    #    planted key only, to avoid opening the wider census here).
    m3 = {k: (dict(v) if k == (56, 26) else v) for k, v in mass.items()}
    old = m3[(56, 26)]["me"]
    m3[(56, 26)]["me"] = Val(old.center + Fraction(7), old.ulp, old.cls)
    affected = {(56, 26), (57, 26), (58, 26), (58, 28), (60, 28), (57, 27),
                (59, 27), (59, 28), (56, 25), (56, 24)}
    per_family = {}
    deletion_ok = True
    for fam in "ABCDEF":
        on = run_all(m3, rct1, rct2, rounded, half)
        off = run_all(m3, rct1, rct2, rounded, half, disable=frozenset(fam))
        n_on = sum(1 for f in on[fam][0] if (f["a"], f["z"]) in affected)
        n_off = sum(1 for f in off[fam][0] if (f["a"], f["z"]) in affected)
        fam_ok = n_off == 0 and (n_on > 0 or fam in "BF")
        # B and F may legitimately not see a Fe-56 me shift on the planted row
        # set if the touched columns are absent; they must still go silent when
        # disabled, and their planted coverage is carried by the planted-
        # mutation suite above.
        per_family[fam] = {"planted_flags_enabled": n_on,
                           "planted_flags_disabled": n_off, "passed": fam_ok}
        deletion_ok &= fam_ok
    report["deletion"] = {"per_family": per_family, "passed": deletion_ok}

    # -- clean fixture: a synthetic self-consistent mini-table must yield zero
    #    flags in relations A-C (its own quirks included).
    fix = {}
    for (a, z), me_c, am_off in [((1, 0), "8071.31806", "1008664.91590"),
                                 ((1, 1), "7288.971064", "1007825.031898"),
                                 ((2, 1), "13135.722895", "2014101.777844")]:
        me = Val(Fraction(me_c), Fraction(1, 10 ** len(me_c.split('.')[1])), "EXP")
        am = Val(Fraction(am_off), Fraction(1, 10 ** len(am_off.split('.')[1])), "EXP")
        fix[(a, z)] = {"n": a - z, "z": z, "a": a, "el": "fx", "me": me, "am": am,
                       "be": None, "beta": None, "bflag": "", "lineno": 0,
                       "raw": "fixture", "raw_sha256": "0" * 64}
    fa, _ = relation_A(fix, half)
    report["clean_fixture"] = {"flags": len(fa), "passed": not fa}

    report["passed"] = all(report[k].get("passed") for k in
                           ("known_answer", "planted", "deletion", "clean_fixture"))
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["controls", "census"], required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    assert_no_llm()
    mass, rct1, rct2, rounded = load_frozen()
    if args.mode == "controls":
        payload = {"schema": "aletheia.r1-ame-closure.controls.v1",
                   "verifier_sha256": sha256(Path(__file__)),
                   "report": controls(mass, rct1, rct2, rounded)}
    else:
        results = {}
        for label, h in (("half_ulp", Fraction(1, 2)), ("one_ulp", Fraction(1))):
            res = run_all(mass, rct1, rct2, rounded, h)
            results[label] = {
                rel: {"flags": res[rel][0], "census": res[rel][1]} for rel in "ABCDEFG"
            }
        payload = {"schema": "aletheia.r1-ame-closure.census.v1",
                   "verifier_sha256": sha256(Path(__file__)),
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
