"""Phase 1: Offline hard_logic_py pattern mining.

Scans data/training data/*.json, categorizes hard_logic_py constraints,
and writes report + CSV to test/hard_logic_pattern_report.{md,csv}.

DO NOT use hard_logic_py at runtime — this script is offline training-data
analysis to help improve the NL parser rules.
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRAINING_DIR = PROJECT_ROOT / "data" / "training data"
OUT_DIR = PROJECT_ROOT / "test"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _parse_budget(snippet: str) -> tuple[str, float] | None:
    # result=restaurant_cost<=1800, result=(total_cost<=3000)
    for pattern, btype in [
        (r"restaurant_cost\s*<=\s*([\d.]+)", "dining"),
        (r"accommodation_cost\s*<=\s*([\d.]+)", "accommodation"),
        (r"total_cost\s*<=\s*([\d.]+)", "total"),
    ]:
        m = re.search(pattern, snippet)
        if m and "result" in snippet:
            return btype, float(m.group(1))
    # free intercity: result=inter_city_transportation_cost<=0
    if re.search(r"inter_city_transportation_cost\s*<=\s*0", snippet) and "result" in snippet:
        return "free_intercity", 0.0
    return None


def main():
    files = sorted(TRAINING_DIR.glob("*.json"))
    print(f"Scanning {len(files)} queries...")

    stats: Counter[str] = Counter()
    must_visit_names: list[str] = []
    required_types: list[str] = []
    forbidden_types: list[str] = []
    transport_modes: Counter[str] = Counter()
    hotel_types: Counter[str] = Counter()
    budget_list: list[tuple[str, float]] = []
    day_counts: Counter[int] = Counter()
    people_counts: Counter[int] = Counter()
    room_counts: Counter[int] = Counter()
    free_attraction = 0
    free_intercity = 0
    raw_unparsed: list[str] = []

    for f in files:
        q = json.loads(f.read_text(encoding="utf-8"))
        hl = q.get("hard_logic_py", [])
        if not hl:
            stats["no_hard_logic"] += 1
            continue
        stats["has_hard_logic"] += 1

        for snippet in hl:
            s = str(snippet).strip()
            stats["total_snippets"] += 1
            matched = False

            # must_visit attraction name: {"Name"}&attraction_name_set
            m = re.search(r"\{\s*\"([^\"]+)\"\s*\}\s*&\s*attraction_name_set", s)
            if m and "not" not in s[: s.index("{")].lower():
                must_visit_names.append(m.group(1))
                stats["must_visit_name"] += 1
                matched = True

            # required attraction type: {"Type"}<=attraction_type_set
            if not matched:
                m = re.search(r"\{\s*\"([^\"]+)\"\s*\}\s*<=\s*attraction_type_set", s)
                if m:
                    required_types.append(m.group(1))
                    stats["required_type"] += 1
                    matched = True

            # forbidden type: not({"Type"}&attraction_type_set)
            if not matched:
                m = re.search(r"not\s*\(\s*\{\s*\"([^\"]+)\"\s*\}\s*&", s, re.IGNORECASE)
                if m:
                    forbidden_types.append(m.group(1))
                    stats["forbidden_type"] += 1
                    matched = True

            # day_count / people_count
            if not matched:
                m = re.search(r"day_count\(plan\)\s*==\s*(\d+)", s)
                if m:
                    day_counts[int(m.group(1))] += 1
                    stats["day_count"] += 1
                    matched = True
            if not matched:
                m = re.search(r"people_count\(plan\)\s*==\s*(\d+)", s)
                if m:
                    people_counts[int(m.group(1))] += 1
                    stats["people_count"] += 1
                    matched = True

            # free constraints
            if not matched and re.search(r"attraction_cost\s*<=\s*0", s) and "result" in s:
                free_attraction += 1
                stats["free_attraction"] += 1
                matched = True
            if not matched and re.search(r"inter_city_transportation_cost\s*<=\s*0", s) and "result" in s:
                free_intercity += 1
                stats["free_intercity"] += 1
                matched = True

            # budget: result=X_cost<=N
            if not matched:
                b = _parse_budget(s)
                if b:
                    budget_list.append(b)
                    stats[f"budget_{b[0]}"] += 1
                    matched = True

            # transport: intercity_transport_type or innercity_transport_type
            if not matched and "intercity_transport" in s and "inner" not in s:
                for mode in ("airplane", "train"):
                    if mode in s:
                        transport_modes[mode] += 1
                stats["intercity_transport"] += 1
                matched = True
            if not matched and "innercity_transport" in s:
                # format: innercity_transport_type(activity)=='metro'
                m = re.search(r"innercity_transport_type\([^)]+\)\s*==\s*'(\w+)'", s)
                if m:
                    transport_modes[m.group(1)] += 1
                stats["innercity_transport"] += 1
                matched = True

            # hotel type: {"Free parking"}&accommodation_type_set
            if not matched:
                hm = re.search(r"\{\s*\"([^\"]+)\"\s*\}\s*(?:&|<=)\s*accommodation_type_set", s)
                if hm:
                    hotel_types[hm.group(1)] += 1
                    stats["hotel_type"] += 1
                    matched = True

            # room count
            if not matched:
                rm = re.search(r"rooms?\([^)]*\)\s*[!=]=\s*(\d+)", s, re.IGNORECASE)
                if rm:
                    room_counts[int(rm.group(1))] += 1
                    stats["room_count"] += 1
                    matched = True

            # tickets
            if not matched and re.search(r"(activity_tickets|metro_tickets|taxi_cars)", s):
                stats["tickets"] += 1
                matched = True

            # cuisine / restaurant
            if not matched and ("cuisine" in s.lower() or "restaurant" in s.lower()):
                stats["cuisine_restaurant"] += 1
                matched = True

            if not matched:
                raw_unparsed.append(s[:150])
                stats["unparsed"] += 1

    # ---- write reports ----
    md_path = OUT_DIR / "hard_logic_pattern_report.md"
    csv_path = OUT_DIR / "hard_logic_pattern_report.csv"

    with open(md_path, "w", encoding="utf-8") as md:
        md.write("# Hard Logic Pattern Report\n\n")
        md.write(f"Scanned: {len(files)} queries, {stats['has_hard_logic']} with hard_logic_py\n\n")

        md.write("## Constraint Distribution\n\n")
        md.write("| Category | Count |\n")
        md.write("|----------|-------|\n")
        for cat in [
            "must_visit_name", "required_type", "forbidden_type",
            "free_attraction", "free_intercity", "day_count", "people_count",
            "intercity_transport", "innercity_transport", "hotel_type",
            "room_count", "budget_dining", "budget_accommodation", "budget_total",
            "tickets", "cuisine_restaurant", "unparsed",
        ]:
            if stats[cat]:
                md.write(f"| {cat} | {stats[cat]} |\n")

        md.write(f"\n## Transport Modes\n\n")
        for mode, cnt in transport_modes.most_common():
            md.write(f"- {mode}: {cnt}\n")

        md.write(f"\n## Hotel Types\n\n")
        for ht, cnt in hotel_types.most_common():
            md.write(f"- {ht}: {cnt}\n")

        md.write(f"\n## Day Counts\n\n")
        for d, cnt in sorted(day_counts.items()):
            md.write(f"- {d} days: {cnt}\n")

        md.write(f"\n## Budget Ranges\n\n")
        for btype in ("dining", "accommodation", "total"):
            vals = [v for t, v in budget_list if t == btype]
            if vals:
                md.write(f"- {btype}: min={min(vals):.0f}, max={max(vals):.0f}, avg={sum(vals)/len(vals):.0f}, n={len(vals)}\n")

        md.write(f"\n## Sample Must-Visit Names (first 30)\n\n")
        for n in must_visit_names[:30]:
            md.write(f"- {n}\n")

        md.write(f"\n## Sample Required Attraction Types (first 20)\n\n")
        for n in required_types[:20]:
            md.write(f"- {n}\n")

        md.write(f"\n## Sample Forbidden Types\n\n")
        for n in sorted(set(forbidden_types)):
            md.write(f"- {n}\n")

        md.write(f"\n## Unparsed Snippets (first 20)\n\n")
        for s in raw_unparsed[:20]:
            md.write(f"- `{s}`\n")

    # CSV
    with open(csv_path, "w", encoding="utf-8", newline="") as cf:
        w = csv.writer(cf)
        w.writerow(["category", "subtype", "value", "count"])
        for cat, cnt in sorted(stats.items()):
            w.writerow([cat, "", "", cnt])
        for mode, cnt in transport_modes.most_common():
            w.writerow(["transport_mode", mode, "", cnt])
        for ht, cnt in hotel_types.most_common():
            w.writerow(["hotel_type", ht, "", cnt])
        for name in must_visit_names:
            w.writerow(["must_visit_name", "", name, 1])
        for t in required_types:
            w.writerow(["required_type", "", t, 1])
        for t in forbidden_types:
            w.writerow(["forbidden_type", "", t, 1])

    print(f"Reports written:")
    print(f"  {md_path}")
    print(f"  {csv_path}")
    print(f"\nSummary: {stats['has_hard_logic']}/{len(files)} queries have hard_logic")
    print(f"  must_visit: {stats['must_visit_name']}")
    print(f"  required_type: {stats['required_type']}")
    print(f"  free_attraction: {free_attraction}")
    print(f"  free_intercity: {free_intercity}")
    print(f"  transport: intercity={stats['intercity_transport']} innercity={stats['innercity_transport']}")
    print(f"  budget: dining={stats['budget_dining']} accommodation={stats['budget_accommodation']} total={stats['budget_total']}")
    print(f"  unparsed: {stats['unparsed']}")


if __name__ == "__main__":
    main()
