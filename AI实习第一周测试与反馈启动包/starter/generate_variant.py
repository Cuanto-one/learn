#!/usr/bin/env python3
"""Generate tiny synthetic assessment inputs with the Python standard library.

This is a data generator, not a log parser, diagnosis algorithm or solution.
The invented JSONL schema is unrelated to any real .dat protocol.
"""

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import random


LOCAL_TZ = timezone(timedelta(hours=8))


def timestamp(value, use_utc=False):
    if use_utc:
        return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return value.astimezone(LOCAL_TZ).isoformat(timespec="milliseconds")


def make_record(source, group, second, start, rng):
    vehicle_id, section, network, role = group
    event_time = start + timedelta(seconds=second)
    delay_ms = rng.choice([50, 120, 350, 1800, 4200])
    record = {
        "vehicle_id": vehicle_id,
        "section": section,
        "network": network,
        "role": role,
        "source": source,
        "sequence": 100 + second,
        "event_time": timestamp(event_time, use_utc=rng.random() < 0.35),
        "ingest_time": timestamp(event_time + timedelta(milliseconds=delay_ms)),
    }
    if source == "status":
        record.update(link_state="disconnected" if second == 8 else "connected", uptime_s=3600 + second)
    else:
        record.update(attached=second != 8, rsrp_dbm=-83 - rng.randrange(0, 14), sinr_db=round(rng.uniform(5, 17), 1))
    return record


def add_input_defects(records, source, rng):
    rows = deepcopy(records)
    exact_duplicate = deepcopy(records[0])
    conflicting_duplicate = deepcopy(records[1])
    moment = datetime.fromisoformat(conflicting_duplicate["event_time"].replace("Z", "+00:00"))
    # An equivalent instant represented with a different timezone offset.
    conflicting_duplicate["event_time"] = timestamp(moment, use_utc=not records[1]["event_time"].endswith("Z"))
    if source == "status":
        conflicting_duplicate["link_state"] = "disconnected"
    else:
        conflicting_duplicate["rsrp_dbm"] = -119
    rows.extend([exact_duplicate, conflicting_duplicate])
    invalid_schema = deepcopy(records[-1])
    invalid_schema["sequence"] = 999
    if source == "status":
        invalid_schema.pop("vehicle_id")
    else:
        invalid_schema["event_time"] = "NOT_A_TIMESTAMP"
    rows.append(invalid_schema)
    rng.shuffle(rows)
    lines = [json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows]
    lines.insert(rng.randrange(len(lines) + 1), '{"source":"' + source + '","broken":')
    return lines


def generate(out_dir, seed, start):
    rng = random.Random(seed)
    first_number, second_number = rng.sample(range(1000, 9999), 2)
    groups = [
        (f"SYN-{first_number}", "A", "A", "main"),
        (f"SYN-{second_number}", "A", "A", "slave"),
        (f"SYN-{first_number}", "B", "B", "main"),
    ]
    # Omitted samples create testable freshness boundaries. Seeds change positions.
    first_status_gap = rng.choice([3, 4, 5])
    second_status_gap = rng.choice([6, 7, 9])
    first_lte_gap = rng.choice([4, 6])
    second_lte_gap = rng.choice([8, 10])
    status_rows, lte_rows = [], []
    for index, group in enumerate(groups):
        status_seconds = list(range(13)) if index < 2 else [0, 4, 8, 12]
        lte_seconds = list(range(0, 13, 2)) if index < 2 else [0, 4, 8, 12]
        if index == 0:
            status_seconds = [v for v in status_seconds if v not in {first_status_gap, first_status_gap + 1}]
            lte_seconds.remove(first_lte_gap)
        elif index == 1:
            status_seconds.remove(second_status_gap)
            lte_seconds.remove(second_lte_gap)
        status_rows.extend(make_record("status", group, v, start, rng) for v in status_seconds)
        lte_rows.extend(make_record("lte", group, v, start, rng) for v in lte_seconds)
    # A present record with a null payload is different from an absent record.
    next(r for r in status_rows if r["vehicle_id"] == groups[1][0] and r["sequence"] == 105)["uptime_s"] = None
    next(r for r in lte_rows if r["vehicle_id"] == groups[1][0] and r["section"] == "A" and r["sequence"] == 102)["rsrp_dbm"] = None
    out_dir.mkdir(parents=True, exist_ok=False)
    for source, records in [("status", status_rows), ("lte", lte_rows)]:
        lines = add_input_defects(records, source, rng)
        (out_dir / f"{source}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    info = {
        "synthetic_only": True,
        "schema_version": "1.0",
        "seed": seed,
        "description": "Invented assessment schema. Not a decoder for real railway .dat files.",
        "window_start": timestamp(start),
        "window_end_exclusive": timestamp(start + timedelta(seconds=13)),
        "grid_ms": 200,
        "status_period_ms": 1000,
        "lte_period_ms": 2000,
        "file_read_order": ["status.jsonl", "lte.jsonl"],
        "groups": [dict(zip(["vehicle_id", "section", "network", "role"], g)) for g in groups],
    }
    (out_dir / "dataset_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="A NEW output directory; existing directories are refused.")
    parser.add_argument("--seed", type=int, default=1022)
    parser.add_argument("--start", default="2026-10-22T08:00:00+08:00", help="Timezone-aware ISO 8601 timestamp.")
    args = parser.parse_args()
    try:
        start = datetime.fromisoformat(args.start.replace("Z", "+00:00"))
        if start.utcoffset() is None:
            raise ValueError("--start must contain a timezone offset or Z")
        info = generate(args.out, args.seed, start)
    except (ValueError, FileExistsError) as exc:
        parser.error(str(exc))
    print(json.dumps({"output_dir": str(args.out.resolve()), "synthetic_only": True, "seed": info["seed"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
