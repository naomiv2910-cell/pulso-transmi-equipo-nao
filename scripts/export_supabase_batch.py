"""Emite lotes JSON compactos para una migración administrativa controlada."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["stations", "observations", "context", "metadata"])
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=2000)
    args = parser.parse_args()

    if args.kind == "metadata":
        print((RAW / "metadata.json").read_text(encoding="utf-8"))
        return

    filename = {
        "stations": "stations.csv",
        "observations": "observations.csv",
        "context": "context.csv",
    }[args.kind]
    frame = pd.read_csv(RAW / filename, dtype={"station_id": "string"})
    batch = frame.iloc[args.offset : args.offset + args.limit]
    print(json.dumps(batch.to_dict(orient="records"), ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()

