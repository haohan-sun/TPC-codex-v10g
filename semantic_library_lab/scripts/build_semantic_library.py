"""Build an isolated semantic library from official local TPC data.

This script only writes under semantic_library_lab/generated.
It reads:
  - demo1/ChinaTravel/chinatravel/environment/database_en
  - demo1/data/training data
  - demo1/skills

It treats hard_logic_py as weak labels for development, never as runtime truth.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = LAB_ROOT.parent
DEMO_ROOT = REPO_ROOT / "demo1"
GENERATED = LAB_ROOT / "generated"

DB_EN = DEMO_ROOT / "ChinaTravel" / "chinatravel" / "environment" / "database_en"
TRAINING_DIR = DEMO_ROOT / "data" / "training data"
SKILLS_DIR = DEMO_ROOT / "skills"


CITY_NAMES = [
    "beijing",
    "shanghai",
    "nanjing",
    "suzhou",
    "hangzhou",
    "shenzhen",
    "chengdu",
    "wuhan",
    "guangzhou",
    "chongqing",
]

CITY_ALIAS_BLOCKLIST = set(CITY_NAMES) | {
    "beijing hotel",
    "shanghai hotel",
    "nanjing hotel",
    "suzhou hotel",
    "hangzhou hotel",
    "shenzhen hotel",
    "chengdu hotel",
    "wuhan hotel",
    "guangzhou hotel",
    "chongqing hotel",
}


STOPWORDS = {
    "the",
    "a",
    "an",
    "of",
    "and",
    "in",
    "at",
    "branch",
    "store",
    "shop",
    "restaurant",
    "hotel",
    "homestay",
    "inn",
}


TYPE_SEED_ALIASES: dict[str, list[str]] = {
    "museum": ["museum", "science museum", "history museum", "exhibition", "gallery"],
    "historical site": ["historical site", "heritage", "ancient", "old town", "ruins", "temple"],
    "commercial district": ["commercial district", "shopping", "mall", "pedestrian street", "business district"],
    "park": ["park", "garden", "scenic area", "green space"],
    "amusement park": ["amusement park", "theme park", "sports entertainment"],
    "cruise": ["cruise", "night cruise", "river cruise", "boat tour"],
    "water street": ["water street", "canal street", "waterside"],
    "zoo": ["zoo", "wildlife", "aquarium"],
    "religious site": ["temple", "mosque", "church", "monastery", "pagoda"],
}


TRANSPORT_ALIASES = {
    "metro": ["metro", "subway", "underground", "by subway", "public transit"],
    "taxi": ["taxi", "cab", "by car", "ride-hailing", "ride hailing"],
    "walk": ["walk", "walking", "on foot"],
    "train": ["train", "rail", "railway", "high-speed rail", "bullet train"],
    "airplane": ["airplane", "plane", "flight", "fly", "by air"],
}


@dataclass
class Entity:
    entity_id: str
    source: str
    city: str
    category: str
    name: str
    canonical_type: str
    raw_type: str
    aliases: list[str]
    metadata: dict[str, Any]


def norm_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def alias_in_text(alias: str, text_norm: str) -> bool:
    start = 0
    while True:
        pos = text_norm.find(alias, start)
        if pos < 0:
            return False
        before_ok = pos == 0 or not text_norm[pos - 1].isalnum()
        end = pos + len(alias)
        after_ok = end == len(text_norm) or not text_norm[end].isalnum()
        if before_ok and after_ok:
            return True
        start = pos + 1


def infer_target_city(text: str) -> str:
    text_norm = norm_text(text)
    mentioned = [city for city in CITY_NAMES if alias_in_text(city, text_norm)]
    for city in mentioned:
        if re.search(rf"\b(to|towards|toward)\s+{re.escape(city)}\b", text_norm):
            return city
    for city in mentioned:
        if re.search(rf"\b(in|visit|visiting)\s+{re.escape(city)}\b", text_norm):
            return city
    return mentioned[0] if len(mentioned) == 1 else ""


def clean_alias(value: str) -> str:
    value = re.sub(r"\([^)]*\)", "", value)
    value = re.sub(r"\[[^]]*\]", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def token_aliases(name: str) -> list[str]:
    aliases: set[str] = set()
    base = clean_alias(name)
    if base:
        aliases.add(base)
    if name:
        aliases.add(name.strip())
    # Remove common branch/store suffixes while keeping enough specificity.
    simplified = re.sub(r"\b(branch|store|shop|hotel|restaurant|homestay|inn)\b", "", base, flags=re.I)
    simplified = re.sub(r"\s+", " ", simplified).strip(" ,-/")
    if simplified and len(simplified) >= 4:
        aliases.add(simplified)
    # Add initials-ish token chunks for long names.
    words = [w for w in re.split(r"[^A-Za-z0-9]+", base) if w and w.lower() not in STOPWORDS]
    if len(words) >= 2:
        aliases.add(" ".join(words[:3]))
        aliases.add(" ".join(words[-3:]))
    return sorted({a for a in aliases if a and norm_text(a) not in CITY_ALIAS_BLOCKLIST})


def canonicalize_type(raw_type: str, name: str = "") -> str:
    text = norm_text(f"{raw_type} {name}")
    for canonical, aliases in TYPE_SEED_ALIASES.items():
        if any(alias in text for alias in aliases):
            return canonical
    if raw_type:
        return norm_text(raw_type)
    return "unknown"


def iter_csv_rows(root: Path, expected_file_fragment: str) -> list[tuple[str, Path, dict[str, str]]]:
    rows: list[tuple[str, Path, dict[str, str]]] = []
    if not root.exists():
        return rows
    for city_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        city = city_dir.name
        for path in sorted(city_dir.glob("*.csv")):
            if expected_file_fragment not in path.name:
                continue
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rows.append((city, path, dict(row)))
    return rows


def build_entities() -> list[Entity]:
    entities: list[Entity] = []
    specs = [
        ("attraction", DB_EN / "attractions", "attractions"),
        ("restaurant", DB_EN / "restaurants", "restaurants"),
        ("hotel", DB_EN / "accommodations", "accommodations"),
    ]
    for category, root, fragment in specs:
        for city, path, row in iter_csv_rows(root, fragment):
            name = row.get("name") or row.get("hotelname_en") or ""
            if not name.strip():
                continue
            raw_type = (
                row.get("type")
                or row.get("featurehoteltype")
                or row.get("cuisine")
                or row.get("category")
                or ""
            )
            canonical = canonicalize_type(raw_type, name)
            aliases = token_aliases(name)
            aliases.extend(token_aliases(row.get("hotelname_en", "")))
            aliases = sorted({a for a in aliases if a})
            eid = f"{category}:{city}:{row.get('id', len(entities))}"
            metadata = {
                k: row.get(k)
                for k in (
                    "id",
                    "lat",
                    "lon",
                    "opentime",
                    "endtime",
                    "price",
                    "recommendmintime",
                    "recommendmaxtime",
                    "numbed",
                    "featurehoteltype",
                    "type",
                )
                if row.get(k) not in (None, "")
            }
            entities.append(
                Entity(
                    entity_id=eid,
                    source=str(path.relative_to(REPO_ROOT)),
                    city=city,
                    category=category,
                    name=name,
                    canonical_type=canonical,
                    raw_type=raw_type,
                    aliases=aliases,
                    metadata=metadata,
                )
            )
    return entities


def parse_braced_strings(logic: str) -> list[str]:
    out: list[str] = []
    for match in re.finditer(r"\{([^{}]*)\}", logic):
        payload = match.group(1)
        for quoted in re.finditer(r'"([^"]+)"', payload):
            out.append(quoted.group(1))
    return out


def is_negated_set_constraint(logic: str, set_name: str) -> bool:
    return bool(
        re.search(rf"not\s*\(\s*\{{[^{{}}]*\}}\s*&\s*{re.escape(set_name)}", logic)
        or re.search(rf"not\s*\(\s*{re.escape(set_name)}\s*&\s*\{{[^{{}}]*\}}", logic)
    )


def parse_hard_logic(logics: list[str]) -> dict[str, Any]:
    labels: dict[str, Any] = {
        "must_visit": [],
        "forbidden_pois": [],
        "attraction_types": [],
        "forbidden_attraction_types": [],
        "restaurant_names": [],
        "forbidden_restaurant_names": [],
        "restaurant_types": [],
        "forbidden_restaurant_types": [],
        "hotel_names": [],
        "hotel_features": [],
        "budget_kinds": [],
        "required_inner_transport": [],
        "required_intercity_transport": [],
        "forbidden_inner_transport": [],
        "forbidden_intercity_transport": [],
        "people_count": None,
        "day_count": None,
        "ticket_count": None,
        "taxi_cars": None,
        "metro_tickets": None,
        "room_type": None,
        "room_count": None,
        "free_attraction": False,
        "free_intercity": False,
        "hotel_distance": False,
        "activity_time_window": False,
        "distance_taxi_rule": False,
        "budget_values": [],
        "raw_logic_count": len(logics),
    }
    for logic in logics:
        strings = parse_braced_strings(logic)
        if "attraction_name_set" in logic:
            target = "forbidden_pois" if is_negated_set_constraint(logic, "attraction_name_set") else "must_visit"
            labels[target].extend(strings)
        if "attraction_type_set" in logic:
            target = (
                "forbidden_attraction_types"
                if is_negated_set_constraint(logic, "attraction_type_set")
                else "attraction_types"
            )
            labels[target].extend(strings)
        if "restaurant_name_set" in logic or "restr" in logic.lower() and "_name_set" in logic:
            negated = is_negated_set_constraint(logic, "restaurant_name_set") or is_negated_set_constraint(
                logic, "restr_name_set"
            )
            labels["forbidden_restaurant_names" if negated else "restaurant_names"].extend(strings)
        if "restaurant_type_set" in logic or "food_type" in logic:
            negated = is_negated_set_constraint(logic, "restaurant_type_set") or is_negated_set_constraint(
                logic, "food_type_set"
            )
            labels["forbidden_restaurant_types" if negated else "restaurant_types"].extend(strings)
        if "hotel_name" in logic or "accommodation_name" in logic:
            labels["hotel_names"].extend(strings)
        if "hotel_feature" in logic or "featurehoteltype" in logic or "accommodation_type" in logic:
            labels["hotel_features"].extend(strings)
        if "accommodation_position" in logic and "poi_distance" in logic:
            labels["hotel_distance"] = True
        if "activity_end_time" in logic or "activity_start_time" in logic:
            labels["activity_time_window"] = True
        if "innercity_transport_distance" in logic and "taxi" in logic.lower():
            labels["distance_taxi_rule"] = True

        for key, field in [
            ("day_count", "day_count"),
            ("people_count", "people_count"),
            ("activity_tickets", "ticket_count"),
            ("metro_tickets", "metro_tickets"),
            ("taxi_cars", "taxi_cars"),
            ("room_type", "room_type"),
            ("room_count", "room_count"),
        ]:
            for match in re.finditer(rf"{key}\([^)]*\)\s*==\s*(\d+)", logic):
                labels[field] = int(match.group(1))
            for match in re.finditer(rf"{key}\([^)]*\)\s*!=\s*(\d+)", logic):
                labels[field] = int(match.group(1))

        for match in re.finditer(r"innercity_transport_type\([^)]*\)\s*==\s*'([^']+)'", logic):
            labels["required_inner_transport"].append(match.group(1))
        for match in re.finditer(r"intercity_transport_type\([^)]*\)\s*==\s*'([^']+)'", logic):
            labels["required_intercity_transport"].append(match.group(1))
        for match in re.finditer(r"innercity_transport_type\([^)]*\)\s*!=\s*'([^']+)'", logic):
            labels["forbidden_inner_transport"].append(match.group(1))
        for match in re.finditer(r"intercity_transport_type\([^)]*\)\s*!=\s*'([^']+)'", logic):
            labels["forbidden_intercity_transport"].append(match.group(1))
        for match in re.finditer(r"\['type'\]\s*!=\s*['\"]([^'\"]+)['\"]", logic):
            mode = match.group(1)
            if mode in {"airplane", "train"}:
                labels["forbidden_intercity_transport"].append(mode)

        if re.search(r"attraction_(?:cost|price)\([^)]*\)\s*==\s*0", logic):
            labels["free_attraction"] = True
        if re.search(r"inter.*(?:cost|price)\([^)]*\)\s*==\s*0", logic, flags=re.I):
            labels["free_intercity"] = True
        for match in re.finditer(r"(?:total_cost|cost|price)\([^)]*\)\s*(?:<=|<|==)\s*(\d+(?:\.\d+)?)", logic):
            labels["budget_values"].append(float(match.group(1)))
        if re.search(r"(?:cost|price|budget).*(?:<=|<|==)", logic, flags=re.I):
            low = logic.lower()
            if "inner_city_transportation" in low or "innercity_transport" in low:
                labels["budget_kinds"].append("innercity_transport")
            elif "inter_city_transportation" in low or "intercity_transport" in low:
                labels["budget_kinds"].append("intercity_transport")
            elif "restaurant" in low or "food" in low or "dining" in low:
                labels["budget_kinds"].append("dining")
            elif "accommodation" in low or "hotel" in low:
                labels["budget_kinds"].append("accommodation")
            elif "attraction" in low or "sightseeing" in low:
                labels["budget_kinds"].append("attraction")
            elif "total_cost" in low:
                labels["budget_kinds"].append("total")

    for key, value in list(labels.items()):
        if isinstance(value, list):
            labels[key] = sorted({v for v in value if v not in (None, "")})
    return labels


def build_hard_logic_labels() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(TRAINING_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        labels = parse_hard_logic(data.get("hard_logic_py") or [])
        rows.append(
            {
                "uid": data.get("uid") or path.stem,
                "text": data.get("nature_language", ""),
                "start_city": data.get("start_city", ""),
                "target_city": data.get("target_city", ""),
                "days": data.get("days"),
                "people_number": data.get("people_number"),
                "labels": labels,
            }
        )
    return rows


def build_alias_index(entities: list[Entity]) -> dict[str, list[dict[str, str]]]:
    index: dict[str, list[dict[str, str]]] = defaultdict(list)
    for entity in entities:
        for alias in entity.aliases:
            key = norm_text(alias)
            if not key:
                continue
            if key in CITY_ALIAS_BLOCKLIST:
                continue
            index[key].append(
                {
                    "entity_id": entity.entity_id,
                    "name": entity.name,
                    "city": entity.city,
                    "category": entity.category,
                    "canonical_type": entity.canonical_type,
                }
            )
    return dict(sorted(index.items()))


def match_text_candidates(
    text: str,
    alias_index: dict[str, list[dict[str, str]]],
    target_city: str = "",
    max_hits: int = 20,
) -> list[dict[str, Any]]:
    text_norm = norm_text(text)
    city = norm_text(target_city) or infer_target_city(text)
    best_by_entity: dict[str, dict[str, Any]] = {}
    for alias, candidates in alias_index.items():
        if len(alias) < 4:
            continue
        if not alias_in_text(alias, text_norm):
            continue
        for cand in candidates[:8]:
            score = len(alias)
            if city and cand.get("city") == city:
                score += 1000
            row = {"alias": alias, "match_type": "bounded_substring", "score": score, **cand}
            old = best_by_entity.get(cand["entity_id"])
            if old is None or score > old["score"]:
                best_by_entity[cand["entity_id"]] = row
    hits = list(best_by_entity.values())
    if city and any(hit.get("city") == city for hit in hits):
        hits = [hit for hit in hits if hit.get("city") == city]
    hits.sort(key=lambda hit: (-hit["score"], -len(hit["alias"]), hit["name"]))
    return hits[:max_hits]


def build_nl_candidates(labels: list[dict[str, Any]], alias_index: dict[str, list[dict[str, str]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in labels:
        text = item.get("text", "")
        hits = match_text_candidates(text, alias_index, target_city=item.get("target_city", ""))
        type_hits = []
        text_norm = norm_text(text)
        for canonical, aliases in TYPE_SEED_ALIASES.items():
            matched = [alias for alias in aliases if alias in text_norm]
            if matched:
                type_hits.append({"canonical_type": canonical, "matched_aliases": matched})
        transport_hits = []
        for mode, aliases in TRANSPORT_ALIASES.items():
            matched = [alias for alias in aliases if alias in text_norm]
            if matched:
                transport_hits.append({"mode": mode, "matched_aliases": matched})
        rows.append(
            {
                "uid": item["uid"],
                "text": text,
                "entity_candidates": hits,
                "type_candidates": type_hits,
                "transport_candidates": transport_hits,
                "weak_labels": item["labels"],
            }
        )
    return rows


def read_skill_notes() -> list[dict[str, str]]:
    notes = []
    for path in sorted(SKILLS_DIR.rglob("*.md")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        notes.append({"path": str(path.relative_to(REPO_ROOT)), "text_preview": text[:2000]})
    return notes


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_report(entities: list[Entity], labels: list[dict[str, Any]], nl_rows: list[dict[str, Any]]) -> None:
    by_category = Counter(e.category for e in entities)
    by_type = Counter(e.canonical_type for e in entities if e.category == "attraction")
    label_counts = Counter()
    for item in labels:
        for key, value in item["labels"].items():
            if isinstance(value, list) and value:
                label_counts[key] += 1
            elif value not in (None, False, [], ""):
                label_counts[key] += 1

    must_visit_examples = []
    for item in labels:
        mv = item["labels"].get("must_visit") or []
        if mv:
            must_visit_examples.append((item["uid"], mv[:3], item["text"][:120]))
        if len(must_visit_examples) >= 12:
            break

    grounded_count = sum(1 for row in nl_rows if row["entity_candidates"] or row["type_candidates"] or row["transport_candidates"])

    lines = [
        "# Semantic Library Pattern Report",
        "",
        "This report is generated outside demo1 and is safe to inspect without changing the planner.",
        "",
        "## Entity Catalog",
        "",
        f"- Total entities: {len(entities)}",
        f"- Categories: {dict(by_category)}",
        "",
        "Top attraction canonical types:",
        "",
    ]
    for t, c in by_type.most_common(20):
        lines.append(f"- {t}: {c}")
    lines.extend(["", "## Weak Label Coverage", ""])
    for key, count in label_counts.most_common():
        lines.append(f"- {key}: {count}")
    lines.extend(["", f"NL candidate grounding coverage: {grounded_count}/{len(nl_rows)}", ""])
    lines.extend(["## Must-Visit Weak Label Examples", ""])
    for uid, mv, text in must_visit_examples:
        lines.append(f"- `{uid}` -> {mv}: {text}")
    lines.extend(
        [
            "",
            "## Integration Notes",
            "",
            "- Use `alias_index.json` for candidate entity matching.",
            "- Use `type_aliases.json` for attraction type normalization.",
            "- Use `hard_logic_labels.jsonl` only as weak training labels.",
            "- Keep DeepSeek/web enrichment optional and offline from official scoring.",
        ]
    )
    (GENERATED / "constraint_patterns_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    GENERATED.mkdir(parents=True, exist_ok=True)
    entities = build_entities()
    labels = build_hard_logic_labels()
    alias_index = build_alias_index(entities)
    nl_rows = build_nl_candidates(labels, alias_index)
    skill_notes = read_skill_notes()

    write_jsonl(GENERATED / "entity_catalog.jsonl", [asdict(e) for e in entities])
    write_json(GENERATED / "alias_index.json", alias_index)
    write_json(GENERATED / "type_aliases.json", TYPE_SEED_ALIASES)
    write_json(GENERATED / "transport_aliases.json", TRANSPORT_ALIASES)
    write_jsonl(GENERATED / "hard_logic_labels.jsonl", labels)
    write_jsonl(GENERATED / "nl_constraint_candidates.jsonl", nl_rows)
    write_json(GENERATED / "skill_notes_index.json", skill_notes)
    write_json(
        GENERATED / "semantic_grounder_seed.json",
        {
            "type_aliases": TYPE_SEED_ALIASES,
            "transport_aliases": TRANSPORT_ALIASES,
            "entity_count": len(entities),
            "weak_label_count": len(labels),
            "notes": "Generated outside demo1; safe for future semantic_grounder_v1.",
        },
    )
    write_report(entities, labels, nl_rows)
    print(
        json.dumps(
            {
                "generated": str(GENERATED),
                "entities": len(entities),
                "weak_labels": len(labels),
                "alias_count": len(alias_index),
                "nl_rows": len(nl_rows),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
