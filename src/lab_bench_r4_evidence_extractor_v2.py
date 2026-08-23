#!/usr/bin/env python3
"""R4_FLAG_ADJUDICATION evidence extractor v2 (2026-08-23).

Post-review rebuild per the Codex A10 items (CODEX_REVIEW_R4_2026-08-23.md):
- starts from CENSUS_V4's 61 CLEAN rows (R2 verifier v3);
- emits every field adjudication may use, including the raw col-77 marker;
- saves ALL header comments (no cap);
- adds an exhaustive whole-dataset explanation search with positive line
  receipts and an explicit negative receipt (scope + patterns + zero-hit);
- replaces the lineage Boolean with explicit states: CONSISTENT_PLACED,
  INCONSISTENT_PLACED, UNPLACED_ENERGY_ONLY, NOT_ELIGIBLE, and records
  whether the source initial level matches the adopted one;
- binds the R2 v3 dependency and archive hashes into its output;
- controls: four end-to-end planted packets (one per non-ambiguous class of
  the mechanical layer), an exact full-packet replay fixture, per-precondition
  deletion mutations that flip planted results, and the two R2 grammar
  fixtures ('L 0.' and 'FL=value uncertainty').
Classification itself stays a separate labeled-judgment step.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import socket
import sys
from fractions import Fraction
from pathlib import Path

ROUTE = Path("/data/adp/investigations/lab_bench_hunt_2026-08-22/04_routes/R4_FLAG_ADJUDICATION")
R2 = ROUTE.parent / "R2_ENSDF_CLOSURE"
RAW = R2 / "raw" / "ensdf_260805"
ZIP_SHA = "sha256:cf9ebf9d8d4064df38041e9f04b414c20476d4b2510bc6695595a9df5c72d95b"[7:]

_s = importlib.util.spec_from_file_location(
    "r2v3", "/data/adp/scripts/lab_bench_r2_ensdf_closure_verifier_v3.py")
r2 = importlib.util.module_from_spec(_s)
_s.loader.exec_module(r2)

K_PRIMARY = r2.K_PRIMARY

OUTLIER_VOCAB = re.compile(
    r"poor(ly)?\s+(energy\s+)?fit|not\s+consistent|inconsistent|excluded\s+from|"
    r"discrepan|does\s+not\s+fit|misfit|omitted\s+(from|in)|fits\s+placement\s+poorly|"
    r"level-energy\s+difference|deviates\s+by|differs\s+by", re.IGNORECASE)
STRUCTURE_VOCAB = re.compile(
    r"two\s+levels|doubl[ey]|reassigned|tentative|uncertain|questionable|"
    r"may\s+be\s+a\s+different\s+level|floating|band\s+.{0,20}shift|"
    r"only\s+members\s+of|not\s+.{0,12}adopted", re.IGNORECASE)
SOURCE_VOCAB = re.compile(
    r"E\([A-Za-z]\)\$?\s*From|from\s+\{?\+?\d{2,3}\}?[A-Za-z]{1,2}.{0,25}(decay|\(n,|\(p,|\(d,|\(a,|\(HI)|"
    r"seen\s+only\s+in|weighted\s+average\s+of", re.IGNORECASE)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dataset_cards_for_text(text: str):
    return list(r2.dataset_iter(text))


def all_dataset_comments(cards):
    out = []
    for ln, line in cards:
        l80 = line.ljust(80)
        if l80[6] in "cCdDtT":
            out.append({"lineno": ln, "text": line.rstrip()})
    return out


def attached_comments(cards, anchor_linenos):
    out = []
    for anchor in anchor_linenos:
        if anchor is None:
            continue
        take = False
        for ln, line in cards:
            l80 = line.ljust(80)
            if ln == anchor:
                take = True
                continue
            if take:
                if l80[6] in "cCdDtT" or l80[5] not in " 1":
                    out.append({"lineno": ln, "text": line.rstrip()})
                elif l80[6] == " " and l80[7] in "LG":
                    break
    return out


def whole_dataset_search(comments, gamma_text, fl_text):
    """Exhaustive explanation search over every dataset comment card."""
    needles = [n for n in (gamma_text, fl_text) if n]
    hits = {"energy_string": [], "outlier_vocab": [], "structure_vocab": [],
            "source_vocab": []}
    for c in comments:
        body = c["text"][9:]
        if any(n in c["text"] for n in needles):
            hits["energy_string"].append(c)
        if OUTLIER_VOCAB.search(body):
            hits["outlier_vocab"].append(c)
        if STRUCTURE_VOCAB.search(body):
            hits["structure_vocab"].append(c)
        if SOURCE_VOCAB.search(body):
            hits["source_vocab"].append(c)
    receipt = {"comment_cards_scanned": len(comments),
               "needles": needles,
               "patterns": {"outlier": OUTLIER_VOCAB.pattern,
                            "structure": STRUCTURE_VOCAB.pattern,
                            "source": SOURCE_VOCAB.pattern},
               "hit_counts": {k: len(v) for k, v in hits.items()},
               "negative": {k: len(v) == 0 for k, v in hits.items()}}
    return hits, receipt


def parse_dataset_levels_gammas(cards):
    """Levels and gammas of one dataset via the v3 grammar, with placement
    verdicts computed directly (not via flag absence)."""
    levels, gammas = [], []
    current_level = None
    for ln, line in cards:
        l80 = line.ljust(80)
        if l80[6] != " ":
            continue
        if l80[7] == "L" and l80[5] == " ":
            q, _ = r2.parse_energy(l80[9:19], l80[19:21])
            levels.append(q)
            current_level = q
        elif l80[7] == "G" and l80[5] == " ":
            q, _ = r2.parse_energy(l80[9:19], l80[19:21])
            if q is not None:
                gammas.append({"q": q, "initial": current_level, "lineno": ln,
                               "raw": line.rstrip()})
    return levels, gammas


def lineage_states(datasets, nucid, a, gq, adopted_initial):
    hits = []
    for dsid, cards in datasets:
        if not cards or not cards[0][1].startswith(nucid):
            continue
        if dsid.upper().startswith("ADOPTED LEVELS"):
            continue
        levels, gammas = parse_dataset_levels_gammas(cards[1:])
        numeric = [q for q in levels if q is not None]
        for g in gammas:
            if abs(g["q"].center - gq.center) > 2 * (g["q"].sigma + gq.sigma):
                continue
            if g["initial"] is None:
                state = "UNPLACED_ENERGY_ONLY"
                same_initial = None
            else:
                recoil = (g["q"].center ** 2) / (2 * a * r2.KEV_PER_U) if a else Fraction(0)
                target = g["initial"].center - g["q"].center - recoil
                tol_base = g["q"].sigma + g["initial"].sigma
                ok = any(q.center < g["initial"].center
                         and abs(target - q.center) <= K_PRIMARY * (tol_base + q.sigma)
                         for q in numeric)
                state = "CONSISTENT_PLACED" if ok else "INCONSISTENT_PLACED"
                same_initial = bool(abs(g["initial"].center - adopted_initial)
                                    <= 5 * (g["initial"].sigma + Fraction(1, 10)))
            hits.append({"dsid": dsid, "lineno": g["lineno"], "raw": g["raw"],
                         "gamma": str(float(g["q"].center)),
                         "initial_level": (str(float(g["initial"].center))
                                           if g["initial"] is not None else None),
                         "state": state, "same_initial_as_adopted": same_initial})
    return hits


def build_packet(datasets, flag):
    nucid = None
    adopted = None
    for dsid, cards in datasets:
        if dsid == flag["dsid"] and cards and cards[0][1][:5].strip() == flag["nucid"]:
            adopted = cards
            nucid = cards[0][1][:5]
            break
    raw80 = flag["raw"].ljust(80)
    gtxt = raw80[9:19].strip()
    gq, _ = r2.parse_energy(raw80[9:19], raw80[19:21])
    level_lineno = None
    for ln, line in adopted:
        l80 = line.ljust(80)
        if l80[6] == " " and l80[7] == "L" and l80[5] == " " and ln < flag["lineno"]:
            level_lineno = ln
    comments = all_dataset_comments(adopted)
    header = []
    for ln, line in adopted:
        l80 = line.ljust(80)
        if l80[6] == " " and l80[7] in "LG" and l80[5] == " ":
            break
        if l80[6] in "cCdDtT":
            header.append({"lineno": ln, "text": line.rstrip()})
    att = attached_comments(adopted, [flag["lineno"], level_lineno])
    fl_text = flag.get("fl")
    hits, search_receipt = whole_dataset_search(comments, gtxt, fl_text)
    lineage = lineage_states(datasets, nucid, flag["a"], gq,
                             Fraction(flag["initial_level"]))
    return {
        "flag": flag,
        "col77": raw80[76],
        "gamma_text": gtxt,
        "attached_comments": att,
        "header_comments": header,
        "whole_dataset_hits": hits,
        "whole_dataset_search_receipt": search_receipt,
        "lineage": lineage,
        "lineage_summary": {
            "consistent_placed_same_initial": sum(
                1 for h in lineage if h["state"] == "CONSISTENT_PLACED"
                and h["same_initial_as_adopted"]),
            "consistent_placed_other_initial": sum(
                1 for h in lineage if h["state"] == "CONSISTENT_PLACED"
                and not h["same_initial_as_adopted"]),
            "inconsistent_placed": sum(1 for h in lineage
                                       if h["state"] == "INCONSISTENT_PLACED"),
            "unplaced_energy_only": sum(1 for h in lineage
                                        if h["state"] == "UNPLACED_ENERGY_ONLY"),
        },
    }


def build_packets():
    census = json.loads((R2 / "receipts" / "CENSUS_V4.json").read_text())
    flags = census["flags_clean"]
    assert len(flags) == 61, len(flags)
    by_file: dict[str, list] = {}
    for f in flags:
        by_file.setdefault(f["source_file"], []).append(f)
    packets = []
    for fname, group in sorted(by_file.items()):
        datasets = dataset_cards_for_text((RAW / fname).read_text(errors="replace"))
        for f in group:
            packets.append(build_packet(datasets, f))
    return packets


def mechanical_class(packet):
    """The mechanical layer of the frozen rubric, literal reading: any
    CONSISTENT_PLACED lineage hit satisfies the mixing precondition."""
    hits = packet["whole_dataset_hits"]
    energy_comment_outlier = any(
        OUTLIER_VOCAB.search(c["text"][9:]) for c in
        (packet["attached_comments"] + hits["energy_string"]))
    ls = packet["lineage_summary"]
    any_consistent = (ls["consistent_placed_same_initial"]
                      + ls["consistent_placed_other_initial"]) > 0
    if energy_comment_outlier:
        return "MECH_DOCUMENTED_OUTLIER"
    if any_consistent:
        return "MECH_MIXING_PRECONDITION"
    if (packet["whole_dataset_search_receipt"]["negative"]["energy_string"]
            and not any_consistent):
        return "MECH_CANDIDATE_PRECONDITION"
    return "MECH_AMBIGUOUS"


# --------------------------------------------------------------- controls

def _card(nucid, cont, typ, e, de, rest="", col80=" "):
    line = f"{nucid:<5}{cont}{' '}{typ} {e:<10}{de:<2}{rest}"
    return line.ljust(79) + col80


def synth_dataset(kind):
    n = " 60FX"
    rows = [f"{n}    ADOPTED LEVELS, GAMMAS".ljust(80)]
    if kind == "outlier":
        rows += [_card(n, " ", "L", "0.000", " 5", "0+"),
                 _card(n, " ", "L", "1000.000", " 5", "2+"),
                 _card(n, " ", "G", "998.700", " 5", "100"),
                 f"{n} cG E$very poor fit and omitted in the fitting".ljust(80)]
        src = [f"{n}    FX B- DECAY".ljust(80)]
    elif kind == "mixing":
        rows += [_card(n, " ", "L", "0.000", " 5", "0+"),
                 _card(n, " ", "L", "1000.000", " 5", "2+"),
                 _card(n, " ", "G", "998.700", " 5", "100")]
        src = [f"{n}    FX B- DECAY".ljust(80),
               _card(n, " ", "L", "0.000", " 5", "0+"),
               _card(n, " ", "L", "998.706", " 5", "2+"),
               _card(n, " ", "G", "998.700", " 5", "100")]
    elif kind == "candidate":
        rows += [_card(n, " ", "L", "0.000", " 5", "0+"),
                 _card(n, " ", "L", "1000.000", " 5", "2+"),
                 _card(n, " ", "G", "998.700", " 5", "100")]
        src = [f"{n}    FX B- DECAY".ljust(80)]
    elif kind == "unplaced_only":
        rows += [_card(n, " ", "L", "0.000", " 5", "0+"),
                 _card(n, " ", "L", "1000.000", " 5", "2+"),
                 _card(n, " ", "G", "998.700", " 5", "100")]
        src = [f"{n}    FX B- DECAY".ljust(80),
               _card(n, " ", "G", "998.700", " 5", "100")]
    text = "\n".join(rows) + "\n\n" + "\n".join(src) + "\n"
    return text


def synth_flag(text):
    datasets = dataset_cards_for_text(text)
    dsid, cards = datasets[0]
    for ln, line in cards:
        l80 = line.ljust(80)
        if l80[6] == " " and l80[7] == "G" and l80[5] == " ":
            return {"nucid": "60FX", "dsid": dsid, "a": 60, "lineno": ln,
                    "raw": line.rstrip(), "initial_level": "1000.0",
                    "fl": None}, datasets
    raise AssertionError


def controls():
    rep = {}
    # R2 grammar fixtures (C663/C664)
    q, _ = r2.parse_energy("0.".ljust(10), "  ")
    g1 = q is not None and q.center == 0 and q.sigma == 1
    fx = (" 60FX    ADOPTED LEVELS, GAMMAS".ljust(80) + "\n"
          + _card(" 60FX", " ", "L", "0.000", " 5", "0+") + "\n"
          + _card(" 60FX", " ", "L", "1000.000", " 5", "2+") + "\n"
          + _card(" 60FX", " ", "G", "999.991", " 5", "100") + "\n"
          + " 60FX2 G FL=1000.000 5".ljust(80) + "\n")
    # FL with uncertainty must resolve, i.e. produce zero REL3 flags
    fl_flags, _ = r2.audit_text(fx, source="fixture")
    g2 = not any(f["relation"] == "R2-REL3_dangling_fl" for f in fl_flags)
    rep["r2_grammar_fixtures"] = {"trailing_dot_parses": g1,
                                  "fl_uncertainty_resolves": g2,
                                  "passed": g1 and g2}

    # end-to-end planted packets, one per mechanical class
    expected = {"outlier": "MECH_DOCUMENTED_OUTLIER",
                "mixing": "MECH_MIXING_PRECONDITION",
                "candidate": "MECH_CANDIDATE_PRECONDITION",
                "unplaced_only": "MECH_CANDIDATE_PRECONDITION"}
    planted = {}
    ok_all = True
    packets = {}
    for kind, want in expected.items():
        flag, datasets = synth_flag(synth_dataset(kind))
        p = build_packet(datasets, flag)
        packets[kind] = p
        got = mechanical_class(p)
        planted[kind] = {"expected": want, "got": got, "passed": got == want}
        ok_all &= got == want
    # unplaced-only must NOT satisfy the mixing precondition
    ok_all &= packets["unplaced_only"]["lineage_summary"]["unplaced_energy_only"] == 1
    planted["unplaced_not_mixing"] = {
        "passed": packets["unplaced_only"]["lineage_summary"]["unplaced_energy_only"] == 1}
    planted["passed"] = ok_all
    rep["planted"] = planted

    # exact full-packet replay
    flag, datasets = synth_flag(synth_dataset("mixing"))
    p1 = json.dumps(build_packet(datasets, flag), sort_keys=True, default=str)
    p2 = json.dumps(build_packet(datasets, flag), sort_keys=True, default=str)
    rep["full_packet_replay"] = {"passed": p1 == p2}

    # deletion mutations: disabling each precondition input flips its plant
    dels = {}
    flag_o, ds_o = synth_flag(synth_dataset("outlier"))
    p = build_packet(ds_o, flag_o)
    p_no_comments = dict(p, attached_comments=[],
                         whole_dataset_hits=dict(p["whole_dataset_hits"], energy_string=[]))
    dels["outlier_without_comment"] = {
        "passed": mechanical_class(p_no_comments) != "MECH_DOCUMENTED_OUTLIER"}
    flag_m, ds_m = synth_flag(synth_dataset("mixing"))
    p = build_packet(ds_m, flag_m)
    p_no_lineage = dict(p, lineage_summary=dict(
        p["lineage_summary"], consistent_placed_same_initial=0,
        consistent_placed_other_initial=0))
    dels["mixing_without_lineage"] = {
        "passed": mechanical_class(p_no_lineage) != "MECH_MIXING_PRECONDITION"}
    flag_c, ds_c = synth_flag(synth_dataset("candidate"))
    p = build_packet(ds_c, flag_c)
    p_broken_negative = dict(p, whole_dataset_search_receipt=dict(
        p["whole_dataset_search_receipt"],
        negative=dict(p["whole_dataset_search_receipt"]["negative"], energy_string=False)))
    dels["candidate_without_negative_receipt"] = {
        "passed": mechanical_class(p_broken_negative) != "MECH_CANDIDATE_PRECONDITION"}
    dels["passed"] = all(v["passed"] for v in dels.values() if isinstance(v, dict))
    rep["deletion"] = dels

    rep["passed"] = all(rep[k]["passed"] for k in
                        ("r2_grammar_fixtures", "planted", "full_packet_replay", "deletion"))
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["controls", "extract"], required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if sha256_file(R2 / "raw" / "ensdf_260805.zip") != ZIP_SHA:
        raise ValueError("archive hash mismatch")
    def _blocked(*_a, **_k):
        raise RuntimeError("network banned")
    socket.socket = _blocked  # type: ignore[assignment]
    binding = {
        "extractor_sha256": sha256_file(Path(__file__)),
        "r2_verifier_v3_sha256": sha256_file(
            Path("/data/adp/scripts/lab_bench_r2_ensdf_closure_verifier_v3.py")),
        "census_v4_sha256": sha256_file(R2 / "receipts" / "CENSUS_V4.json"),
        "zip_sha256": ZIP_SHA,
    }
    if args.mode == "controls":
        payload = {"schema": "aletheia.r4-adjudication.controls.v2",
                   "binding": binding, "report": controls()}
    else:
        packets = build_packets()
        for p in packets:
            p["mechanical_class"] = mechanical_class(p)
        payload = {"schema": "aletheia.r4-adjudication.evidence.v2",
                   "binding": binding,
                   "packet_count": len(packets), "packets": packets}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    ok = payload.get("report", {}).get("passed", True)
    print(json.dumps({"mode": args.mode, "passed": ok,
                      "packets": payload.get("packet_count"), "out": str(args.out)}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
