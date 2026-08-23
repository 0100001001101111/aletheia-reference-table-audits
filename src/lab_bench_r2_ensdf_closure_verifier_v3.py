#!/usr/bin/env python3
"""R2_ENSDF_CLOSURE verifier v3 (2026-08-23).

Grammar repairs per C663/C664 (PREREG_AMENDMENT_V5.json): trailing-dot
energies parse as numeric; FL= references may carry an uncertainty token.
Otherwise byte-equivalent logic to v2.

Implements PREREG_AMENDMENT_V4.json after the Codex A10 review refuted the
v1 census layer: registered FL rule with no cushion, FL_MALFORMED and
FL_AMBIGUOUS classes, per-dataset source-ruled missing gamma uncertainties,
and CLEAN versus PROXY flag separation. v1 stays untouched on disk (C635).
Arithmetic core (exact fractions, recoil, K=5/K=10/0.5 keV) unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import socket
import sys
from fractions import Fraction
from pathlib import Path

ROUTE = Path("/data/adp/investigations/lab_bench_hunt_2026-08-22/04_routes/R2_ENSDF_CLOSURE")
RAW = ROUTE / "raw" / "ensdf_260805"
ZIP_SHA = "sha256:cf9ebf9d8d4064df38041e9f04b414c20476d4b2510bc6695595a9df5c72d95b"[7:]
KEV_PER_U = Fraction("931494.10242")
NUMERIC_RE = re.compile(r"^[+-]?\d+(\.\d*)?([Ee][+-]?\d+)?$")
K_PRIMARY = Fraction(5)
K_CONFIRM = Fraction(10)
ABS_FLOOR_KEV = Fraction(1, 2)
MISSING_DE_RE = re.compile(r"DE\|?g\s*=\s*([0-9.]+)\s*KEV", re.IGNORECASE)


def assert_no_llm() -> None:
    def _blocked(*_a, **_k):
        raise RuntimeError("network access is banned in the scoring path")
    socket.socket = _blocked  # type: ignore[assignment]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Qty:
    __slots__ = ("center", "sigma", "cls", "text", "proxy")

    def __init__(self, center, sigma, cls, text, proxy):
        self.center, self.sigma, self.cls, self.text, self.proxy = (
            center, sigma, cls, text, proxy)


def parse_energy(e_field: str, de_field: str, missing_de_sigma=None):
    t = e_field.strip()
    if not t:
        return None, "EMPTY"
    if not NUMERIC_RE.match(t):
        return None, "OFFSET"
    bare_dot = t.endswith('.')
    if bare_dot:
        t = t + '0'
    center = Fraction(t) if "e" not in t.lower() else (
        Fraction(t.upper().split("E")[0]) * Fraction(10) ** int(t.upper().split("E")[1]))
    mant = t.upper().split("E")[0]
    decimals = 0 if bare_dot else (len(mant.split(".")[1]) if "." in mant else 0)
    ulp = Fraction(1, 10 ** decimals)
    if "E" in t.upper():
        ulp *= Fraction(10) ** int(t.upper().split("E")[1])
    de = de_field.strip()
    if de.isdigit() and de != "0":
        return Qty(center, Fraction(int(de)) * ulp, "NUMERIC_DE", t, False), None
    if missing_de_sigma is not None:
        return Qty(center, missing_de_sigma, "BLANK_DE_SOURCE_RULE", t, False), None
    return Qty(center, ulp, "BLANK_DE_PROXY", t, True), None


def dataset_iter(text: str):
    cards, dsid = [], None
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            if dsid is not None:
                yield dsid, cards
            cards, dsid = [], None
            continue
        if dsid is None:
            dsid = line[9:39].strip()
            cards = [(lineno, line)]
        else:
            cards.append((lineno, line))
    if dsid is not None:
        yield dsid, cards


CENSUS_KEYS = ["eligible_search", "eligible_fl", "ORPHAN", "OFFSET", "EMPTY",
               "QUESTIONABLE", "UNOBSERVED", "NONNUM_INITIAL", "NUMERIC_DE",
               "BLANK_DE_PROXY", "BLANK_DE_SOURCE_RULE", "levels_numeric",
               "levels_nonnumeric", "gammas_total", "tail_beyond_1x",
               "tail_beyond_2x", "FL_UNKNOWN", "FL_OFFSET", "FL_MALFORMED",
               "FL_AMBIGUOUS"]


def dataset_missing_de(cards):
    """Source-ruled missing gamma uncertainty: a comment stating a keV value
    for missing gamma-ray uncertainties (e.g. 193Os)."""
    blob = []
    for _, line in cards:
        line = line.ljust(80)
        if line[6] in "cCdDtT":
            blob.append(line[9:80])
    text = " ".join(blob)
    if "MISSING" in text.upper():
        m = MISSING_DE_RE.search(text)
        if m:
            try:
                return Fraction(m.group(1))
            except (ValueError, ZeroDivisionError):
                return None
    return None


def audit_dataset(nucid_a: int, cards, disable=frozenset()):
    census = {k: 0 for k in CENSUS_KEYS}
    missing_de = dataset_missing_de(cards)
    levels, flags, pending = [], [], []
    current_level, current_gamma = None, None

    for lineno, line in cards:
        line = line.ljust(80)
        cont, com, typ = line[5], line[6], line[7]
        if com != " ":
            continue
        if typ == "L" and cont == " ":
            q, _ = parse_energy(line[9:19], line[19:21])
            if q is None:
                levels.append(None)
                census["levels_nonnumeric"] += 1
                current_level = "NONNUM"
            else:
                levels.append(q)
                census["levels_numeric"] += 1
                current_level = len(levels) - 1
            current_gamma = None
        elif typ == "G" and cont == " ":
            census["gammas_total"] += 1
            current_gamma = None
            if line[79] == "?":
                census["QUESTIONABLE"] += 1
                continue
            if line[79] == "S":
                census["UNOBSERVED"] += 1
                continue
            if current_level is None:
                census["ORPHAN"] += 1
                continue
            if current_level == "NONNUM":
                census["NONNUM_INITIAL"] += 1
                continue
            q, excl = parse_energy(line[9:19], line[19:21], missing_de)
            if q is None:
                census[excl] += 1
                continue
            census[q.cls] += 1
            current_gamma = {"q": q, "level_idx": current_level,
                             "lineno": lineno, "raw": line, "fl": []}
            pending.append(current_gamma)
        elif typ == "G" and cont not in " 1" and current_gamma is not None:
            for m in re.finditer(r"FL=([^$]*)", line[9:80]):
                tok = m.group(1).split("$")[0]
                parts = tok.split()
                if parts and re.fullmatch(r"[0-9.]+", parts[0]) and len(parts) > 1 and re.fullmatch(r"\d+", parts[1]):
                    tok = parts[0]  # C664: value followed by its uncertainty
                current_gamma["fl"].append(tok)

    numeric = sorted((q.center, i) for i, q in enumerate(levels) if q is not None)

    for g in pending:
        q, li = g["q"], levels[g["level_idx"]]
        recoil = (q.center * q.center) / (2 * nucid_a * KEV_PER_U) if nucid_a else Fraction(0)
        target = li.center - q.center - recoil
        tol_base = q.sigma + li.sigma
        base = {"a": nucid_a, "lineno": g["lineno"], "raw": g["raw"].rstrip(),
                "raw_sha256": hashlib.sha256(g["raw"].rstrip("\n").encode()).hexdigest(),
                "gamma": str(float(q.center)), "gamma_de_class": q.cls,
                "initial_level": str(float(li.center)),
                "target_kev": str(float(target))}
        fl_raw = g["fl"]
        if fl_raw:
            # malformed: raw capture starts with whitespace or is empty
            if any(tok != tok.lstrip() or not tok.strip() for tok in fl_raw):
                census["FL_MALFORMED"] += 1
                continue
            tokens = sorted({tok.strip() for tok in fl_raw})
            if len(tokens) > 1:
                census["FL_AMBIGUOUS"] += 1
                continue
            fl_text = tokens[0]
            if fl_text == "?":
                census["FL_UNKNOWN"] += 1
                continue
            if any(ch.isalpha() for ch in fl_text):
                census["FL_OFFSET"] += 1
                continue
            census["eligible_fl"] += 1
            match = None
            for q2 in levels:
                if q2 is not None and q2.text == fl_text:
                    match = q2
                    break
            if match is None and NUMERIC_RE.match(fl_text):
                flc = Fraction(fl_text)
                best = None
                for q2 in levels:
                    if q2 is not None:
                        gap = abs(q2.center - flc)
                        if gap <= q2.sigma and (best is None or gap < best[0]):
                            best = (gap, q2)
                if best:
                    match = best[1]
            if match is None:
                if "REL3" not in disable:
                    flags.append({**base, "relation": "R2-REL3_dangling_fl",
                                  "fl": fl_text,
                                  "proxy": q.proxy or li.proxy})
                continue
            dev = abs(target - match.center)
            tol = tol_base + match.sigma
            if dev > tol:
                census["tail_beyond_1x"] += 1
            if dev > 2 * tol:
                census["tail_beyond_2x"] += 1
            if ("REL2" not in disable and dev > K_PRIMARY * tol
                    and dev > K_CONFIRM * tol and dev > ABS_FLOOR_KEV):
                flags.append({**base, "relation": "R2-REL2_fl_inconsistent",
                              "fl": fl_text, "fl_level": str(float(match.center)),
                              "deviation_kev": str(float(dev)),
                              "tolerance_1x_kev": str(float(tol)),
                              "proxy": q.proxy or li.proxy or match.proxy})
        else:
            census["eligible_search"] += 1
            best_dev, best_pair = None, None
            for c, idx in numeric:
                q2 = levels[idx]
                if q2.center >= li.center:
                    continue
                dev = abs(target - q2.center)
                if best_dev is None or dev < best_dev:
                    best_dev, best_pair = dev, q2
            if best_dev is None:
                continue
            tol = tol_base + best_pair.sigma
            ok5 = any(
                abs(target - levels[idx].center) <= K_PRIMARY * (tol_base + levels[idx].sigma)
                for c, idx in numeric if levels[idx].center < li.center)
            ok10 = any(
                abs(target - levels[idx].center) <= K_CONFIRM * (tol_base + levels[idx].sigma)
                for c, idx in numeric if levels[idx].center < li.center)
            if best_dev > tol:
                census["tail_beyond_1x"] += 1
            if best_dev > 2 * tol:
                census["tail_beyond_2x"] += 1
            if ("REL1" not in disable and not ok5 and not ok10
                    and best_dev > ABS_FLOOR_KEV):
                flags.append({**base, "relation": "R2-REL1_no_destination",
                              "min_deviation_kev": str(float(best_dev)),
                              "proxy": q.proxy or li.proxy or best_pair.proxy})
    return flags, census


ID_RE = re.compile(r"^\s*(\d+)([A-Z]{1,2})$")


def nucid_mass(nucid: str) -> int:
    m = ID_RE.match(nucid.strip())
    return int(m.group(1)) if m else 0


def audit_text(text: str, disable=frozenset(), source=""):
    all_flags, chain_census = [], {}
    all_lines = text.splitlines()
    for dsid, cards in dataset_iter(text):
        if not dsid.upper().startswith("ADOPTED LEVELS"):
            continue
        nucid = cards[0][1][:5]
        a = nucid_mass(nucid)
        flags, census = audit_dataset(a, cards[1:], disable)
        for f in flags:
            f["nucid"] = nucid.strip()
            f["dsid"] = dsid
            f["source_file"] = source
            ln = f["lineno"]
            f["context"] = [all_lines[i].rstrip() for i in
                            range(max(0, ln - 4), min(len(all_lines), ln + 3))]
        all_flags.extend(flags)
        agg = chain_census.setdefault(str(a), {})
        for k, v in census.items():
            agg[k] = agg.get(k, 0) + v
    return all_flags, chain_census


def run_archive(disable=frozenset()):
    files = sorted(RAW.glob("ensdf.*"))
    if len(files) != 300:
        raise ValueError(f"expected 300 archive files, found {len(files)}")
    all_flags, census = [], {}
    for path in files:
        flags, chains = audit_text(path.read_text(errors="replace"), disable, path.name)
        all_flags.extend(flags)
        for chain, c in chains.items():
            agg = census.setdefault(chain, {})
            for k, v in c.items():
                agg[k] = agg.get(k, 0) + v
    return all_flags, census


def _card(nucid, cont, typ, e, de, rest="", col80=" "):
    line = f"{nucid:<5}{cont}{' '}{typ} {e:<10}{de:<2}{rest}"
    line = line.ljust(79) + col80
    assert len(line) == 80
    return line


def build_fixture(missing_de_comment=False) -> str:
    n = " 60FX"
    rows = [f"{n}    ADOPTED LEVELS, GAMMAS".ljust(80)]
    if missing_de_comment:
        rows.append(f"{n} cL E$assuming DEg=0.5 keV for missing g-ray uncertainty".ljust(80))
    rows += [
        _card(n, " ", "L", "0.000", " 5", "0+"),
        _card(n, " ", "L", "1000.000", " 5", "2+"),
        _card(n, " ", "G", "999.991", " 5", "100      E2"),
        _card(n, " ", "L", "2500.000", "10", "4+"),
        _card(n, " ", "G", "1499.980", "10", "100      E2"),
        f"{n}2 G FL=1000.000".ljust(80),
        _card(n, " ", "G", "2499.944", "10", "10       E2"),
        _card(n, " ", "G", "1500.0", "  ", "5"),
        _card(n, " ", "G", "150+X", "  ", "1"),
        _card(n, " ", "L", "X", "  ", "3+"),
        _card(n, " ", "G", "500.0", "  ", "50"),
        _card(n, " ", "L", "3000+X", "  ", "(5+)"),
        _card(n, " ", "G", "123.4", " 5", "1", col80="?"),
        _card(n, " ", "G", "77.7", " 5", "1", col80="S"),
    ]
    return "\n".join(rows) + "\n"


def controls() -> dict:
    report = {}
    FIXTURE = build_fixture()

    flags, census = audit_text(FIXTURE, source="fixture")
    c60 = census.get("60", {})
    quirks = (c60.get("OFFSET", 0) >= 1 and c60.get("QUESTIONABLE", 0) >= 1
              and c60.get("UNOBSERVED", 0) >= 1 and c60.get("NONNUM_INITIAL", 0) >= 1
              and c60.get("eligible_fl", 0) >= 1 and c60.get("BLANK_DE_PROXY", 0) >= 1)
    report["clean_fixture"] = {"flags": len(flags), "census": c60,
                               "quirks_exercised": quirks,
                               "passed": not flags and quirks}

    # malformed FL, ambiguous FL, and registered-rule dangling FL
    mal = FIXTURE.replace("FL=1000.000", "FL= 1000.000")
    mflags, mcen = audit_text(mal, source="fixture")
    mal_ok = mcen["60"].get("FL_MALFORMED", 0) == 1 and not mflags
    amb = FIXTURE.replace(" 60FX2 G FL=1000.000".ljust(80),
                          (" 60FX2 G FL=1000.000$FL=2500.000").ljust(80))
    aflags, acen = audit_text(amb, source="fixture")
    amb_ok = acen["60"].get("FL_AMBIGUOUS", 0) == 1 and not aflags
    # dangling under the registered rule: 0.2 keV from a level with 0.005 sigma
    dang = FIXTURE.replace("FL=1000.000", "FL=1000.200")
    dflags, _ = audit_text(dang, source="fixture")
    dang_ok = any(f["relation"] == "R2-REL3_dangling_fl" for f in dflags)
    # C634 counterfactual: the padded matcher would have accepted 1000.200
    report["fl_rule"] = {"malformed_classified": mal_ok, "ambiguous_classified": amb_ok,
                        "registered_rule_dangles_0p2kev": dang_ok,
                        "passed": mal_ok and amb_ok and dang_ok}

    # source-ruled missing DE: same displacement flags under proxy sigma but
    # not under the dataset's stated 0.5 keV rule
    shifted_proxy = build_fixture(False).replace("1500.0", "1501.2")
    p_flags, p_cen = audit_text(shifted_proxy, source="fixture")
    proxy_catches = any(f["relation"] == "R2-REL1_no_destination" and f["proxy"]
                        for f in p_flags)
    shifted_ruled = build_fixture(True).replace("1500.0", "1501.2")
    r_flags, r_cen = audit_text(shifted_ruled, source="fixture")
    ruled_quiet = not any(f["relation"] == "R2-REL1_no_destination" for f in r_flags)
    ruled_class = r_cen["60"].get("BLANK_DE_SOURCE_RULE", 0) >= 1
    report["missing_de_rule"] = {"proxy_flags_shift": proxy_catches,
                                 "source_rule_absorbs_shift": ruled_quiet,
                                 "source_rule_class_counted": ruled_class,
                                 "passed": proxy_catches and ruled_quiet and ruled_class}

    text = (RAW / "ensdf.060").read_text(errors="replace")
    ni = ""
    for dsid, cards in dataset_iter(text):
        if dsid.upper().startswith("ADOPTED LEVELS") and cards[0][1].startswith(" 60NI"):
            ni = "\n".join(l for _, l in cards) + "\n"
            break
    flags_ni, _ = audit_text(ni, source="ensdf.060:60NI")
    named = {"1332.501", "1173.228", "826.06", "2158.57", "2505.692", "952.4"}
    named_flagged = [f for f in flags_ni if f["raw"][9:19].strip() in named]
    report["known_answer"] = {"ni60_flags_total": len(flags_ni),
                              "named_wellknown_gammas_flagged": len(named_flagged),
                              "passed": not named_flagged}

    scatter = FIXTURE.replace("999.991", "999.983", 1)
    sflags, _ = audit_text(scatter, source="fixture")
    report["scatter_guard"] = {"flags": len(sflags), "passed": not sflags}

    plants = [
        ("small_up", "999.991", "1000.991", "R2-REL1_no_destination"),
        ("small_down", "999.991", "998.991", "R2-REL1_no_destination"),
        ("large_up", "2499.944", "2399.944", "R2-REL1_no_destination"),
        ("fl_break", "1499.980", "1497.980", "R2-REL2_fl_inconsistent"),
        ("fl_dangle", "FL=1000.000", "FL=1051.234", "R2-REL3_dangling_fl"),
    ]
    planted, all_ok = {}, True
    for name, old, new, want in plants:
        mutated = FIXTURE.replace(old, new, 1)
        assert mutated != FIXTURE, name
        mflags2, _ = audit_text(mutated, source="fixture")
        hit = any(f["relation"] == want for f in mflags2)
        planted[name] = {"expected_relation": want, "caught": hit}
        all_ok &= hit
    planted["passed"] = all_ok
    report["planted"] = planted

    deletions, del_ok = {}, True
    for name, old, new, want, dis in [
        ("REL1_off", "999.991", "998.991", "R2-REL1_no_destination", "REL1"),
        ("REL2_off", "1499.980", "1497.980", "R2-REL2_fl_inconsistent", "REL2"),
        ("REL3_off", "FL=1000.000", "FL=1051.234", "R2-REL3_dangling_fl", "REL3"),
    ]:
        mutated = FIXTURE.replace(old, new, 1)
        on, _ = audit_text(mutated, source="fixture")
        off, _ = audit_text(mutated, disable=frozenset([dis]), source="fixture")
        on_hit = any(f["relation"] == want for f in on)
        off_hit = any(f["relation"] == want for f in off)
        ok = on_hit and not off_hit
        deletions[name] = {"detected_enabled": on_hit, "detected_disabled": off_hit,
                           "passed": ok}
        del_ok &= ok
    deletions["passed"] = del_ok
    report["deletion"] = deletions

    report["passed"] = all(report[k]["passed"] for k in
                           ("clean_fixture", "fl_rule", "missing_de_rule",
                            "known_answer", "scatter_guard", "planted", "deletion"))
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["controls", "census"], required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    assert_no_llm()
    if sha256_file(ROUTE / "raw" / "ensdf_260805.zip") != ZIP_SHA:
        raise ValueError("archive hash mismatch")
    if args.mode == "controls":
        payload = {"schema": "aletheia.r2-ensdf-closure.controls.v3",
                   "verifier_sha256": sha256_file(Path(__file__)),
                   "report": controls()}
    else:
        flags, census = run_archive()
        clean = [f for f in flags if not f.get("proxy")]
        proxy = [f for f in flags if f.get("proxy")]
        payload = {"schema": "aletheia.r2-ensdf-closure.census.v3",
                   "verifier_sha256": sha256_file(Path(__file__)),
                   "rule": "registered FL rule (no cushion); K=5 AND K=10 AND >0.5 keV; source-ruled missing DE; CLEAN vs PROXY split",
                   "flag_count_total": len(flags),
                   "flag_count_clean": len(clean),
                   "flag_count_proxy": len(proxy),
                   "flags_clean": clean, "flags_proxy": proxy,
                   "census_by_chain": census}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    ok = payload.get("report", {}).get("passed", True)
    print(json.dumps({"mode": args.mode, "passed": ok,
                      "clean": payload.get("flag_count_clean"),
                      "proxy": payload.get("flag_count_proxy"),
                      "out": str(args.out)}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
