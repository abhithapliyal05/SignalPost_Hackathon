#!/usr/bin/env python3
"""Write two disjoint, reproducible 100-company samples from the public universe.

data/dev100.txt is for tuning; data/val100.txt is held out and never tuned on.
"""

from __future__ import annotations

import argparse
import gzip
import json
import random
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", default="cache/signalpost-universe.jsonl.gz")
    parser.add_argument("--seed", type=int, default=20261014)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--out-dir", default="data")
    args = parser.parse_args()

    with gzip.open(args.universe, "rt", encoding="utf-8") as handle:
        orgs = sorted(json.loads(line)["organisation_number"] for line in handle if line.strip())
    chosen = random.Random(args.seed).sample(orgs, 2 * args.count)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "dev100.txt").write_text("\n".join(chosen[: args.count]) + "\n", encoding="utf-8")
    (out / "val100.txt").write_text("\n".join(chosen[args.count :]) + "\n", encoding="utf-8")
    print(f"Sampled {args.count} dev + {args.count} val from {len(orgs):,} organisations (seed {args.seed})")


if __name__ == "__main__":
    main()
