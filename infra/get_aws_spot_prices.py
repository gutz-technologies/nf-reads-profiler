#!/usr/bin/env python3
"""Graviton spot prices + placement scores in a region, sorted by value.

Helps pick instance types for the Batch queues (e.g. spot-metaphlan). Lists every
in-region instance type in the requested families, pulls the cheapest current spot
price across AZs, scores how likely you are to actually launch N of each, and ranks
by value. Defaults to all Graviton4 (8g) families in the region.

  ./get_aws_spot_prices.py                       # all Graviton4 families, us-east-2, by $/vCPU
  ./get_aws_spot_prices.py -f r8g m8g c8g        # only these families
  ./get_aws_spot_prices.py -n 4                  # score odds of launching 4 of each
  ./get_aws_spot_prices.py --sort gb             # rank by $/GB instead

############################################################################
# THE QUERY QUOTA IS THE SCARCE RESOURCE — MANAGE IT DELIBERATELY.
#
# The SpotPlacement column comes from EC2 get-spot-placement-scores, which is
# capped by a HARD 24-HOUR ACCOUNT QUOTA on the number of DISTINCT
# "configurations" you may request. A configuration = (instance-type set,
# target-capacity, region). Each NEW (type, -n value, region) triple you ask
# about SPENDS ONE unit of that daily budget. Once spent it does not come back
# until 24h elapse (or you raise the quota in Service Quotas > EC2 >
# "Spot placement score").
#
# Practical consequences:
#   * Re-running the SAME family list and SAME -n within 24h is FREE — those
#     configs are cached as "retryable" and return a real score again.
#   * Widening -f (more types) or changing -n mints NEW configs and burns budget.
#     A bare run over all Graviton families mints ~100 configs in one shot.
#   * Over budget => that type's column shows `quota` (not an error, not 0 odds —
#     just "no budget left to ask today"). Configs you already spent today still
#     return numbers.
#
# Rule of thumb: settle on your real candidate type list FIRST, then run once to
# spend the budget intentionally; iterate freely for the rest of the 24h.
############################################################################
"""

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

DEFAULT_REGION = "us-east-2"
# All Graviton4 ("8g") families AWS offers in us-east-2 (verified via
# describe-instance-types). c8g=compute, m8g=general, r8g=memory, x8g=high-mem,
# i8g/i8ge=storage; d=local NVMe, n=high network.
DEFAULT_FAMILIES = [
    "c8g", "c8gd", "c8gn",
    "m8g", "m8gd",
    "r8g", "r8gd",
    "x8g",
    "i8g", "i8ge",
]
PRODUCT = "Linux/UNIX"


def aws(region, *args):
    r = subprocess.run(
        ["aws", "--region", region] + list(args), capture_output=True, text=True
    )
    if r.returncode != 0:
        print(f"ERROR: {r.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return json.loads(r.stdout)


def list_types(region, families):
    """In-region arm64 (Graviton) instance types.

    If `families` is None, return every arm64 type; otherwise keep only those
    whose family prefix is in `families`.
    """
    data = aws(
        region, "ec2", "describe-instance-types",
        "--filters", "Name=processor-info.supported-architecture,Values=arm64",
        "--query", "InstanceTypes[].[InstanceType,VCpuInfo.DefaultVCpus,MemoryInfo.SizeInMiB]",
        "--output", "json",
    )
    fams = set(families) if families else None
    out = []
    for itype, vcpu, memmib in data:
        if fams is None or itype.split(".", 1)[0] in fams:
            out.append((itype, int(vcpu), memmib / 1024.0))
    return out


def placement_score(region, itype, target_capacity):
    """Spot placement score (1-10) for getting `target_capacity` instances of
    `itype` in `region`. Higher = more likely to be fulfilled; None on error.

    get-spot-placement-scores is the only AWS API that estimates spot-capacity
    likelihood for a request of a given SIZE — interrupt frequency only says how
    often a running instance gets reclaimed, not whether you can launch N now.
    The score is a coarse 1-10 bucket, recomputed by AWS continuously, and is an
    estimate, NOT a guarantee or a probability. Scored region-wide (best AZ).
    """
    import time

    cmd = ["aws", "--region", region, "ec2", "get-spot-placement-scores",
           "--instance-types", itype,
           "--target-capacity", str(target_capacity),
           "--target-capacity-unit-type", "units",
           "--region-names", region,
           "--query", "SpotPlacementScores[0].Score",
           "--output", "json"]
    # Two distinct limits: plain throttling (retryable) vs MaxConfigLimitExceeded
    # — a 24h quota on the number of DISTINCT configs (type+capacity+region) you
    # can request. Re-querying a config used in the last 24h is free; a new one
    # past quota returns "quota" until the budget resets or is raised in Service
    # Quotas (EC2 > "Spot placement score").
    for attempt in range(5):
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            try:
                return json.loads(r.stdout)
            except Exception:
                return None
        if "MaxConfigLimitExceeded" in r.stderr:
            return "quota"
        if "RequestLimitExceeded" in r.stderr or "Throttling" in r.stderr:
            time.sleep(2 ** attempt)
            continue
        return None
    return None


def cheapest_spot(region, itype):
    """Lowest current spot price across all AZs, or None if unavailable."""
    from datetime import datetime, timezone

    data = aws(
        region, "ec2", "describe-spot-price-history",
        "--instance-types", itype,
        "--product-descriptions", PRODUCT,
        "--start-time", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "--query", "SpotPriceHistory[].SpotPrice",
        "--output", "json",
    )
    prices = [float(p) for p in data]
    return min(prices) if prices else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-r", "--region", default=DEFAULT_REGION)
    ap.add_argument("-f", "--families", nargs="+", default=DEFAULT_FAMILIES,
                    help=f"instance-type family prefixes (default: {' '.join(DEFAULT_FAMILIES)})")
    ap.add_argument("-a", "--all", action="store_true",
                    help="every arm64 (Graviton) type, ignore --families")
    ap.add_argument("--sort", choices=["vcpu", "gb", "price"], default="vcpu",
                    help="rank by $/vCPU (default), $/GB, or absolute $/hr")
    ap.add_argument("-n", "--target-capacity", type=int, default=2,
                    help="instances per type to score for availability (default: 2)")
    args = ap.parse_args()

    families = None if args.all else args.families
    fam_label = "all Graviton" if args.all else " ".join(args.families)
    types = list_types(args.region, families)
    if not types:
        print(f"No in-region arm64 types found for: {fam_label}", file=sys.stderr)
        sys.exit(1)

    rows = []
    with ThreadPoolExecutor(max_workers=16) as ex:
        prices = list(ex.map(lambda t: cheapest_spot(args.region, t[0]), types))
        scores = list(ex.map(
            lambda t: placement_score(args.region, t[0], args.target_capacity), types))
        for (itype, vcpu, memgib), price, score in zip(types, prices, scores):
            if price is None:
                continue
            rows.append((itype, vcpu, memgib, price, price / memgib, price / vcpu, score))

    sort_idx = {"price": 3, "gb": 4, "vcpu": 5}[args.sort]
    rows.sort(key=lambda r: r[sort_idx])

    print(f"# Graviton spot prices — {args.region} — families: {' '.join(args.families)} "
          f"(sorted by ${'/vCPU' if args.sort == 'vcpu' else '/GB' if args.sort == 'gb' else '/hr'})")
    print(f"# SpotPlacement = placement score 1-10 for launching {args.target_capacity} "
          f"(-n) of this type region-wide; 10=best estimate (NOT a guarantee), "
          f"'quota'=24h config budget spent (see header)")
    print("TYPE,Family,vCPU,MemGiB,Spot$/hr,$/GB,$/vCPU,SpotPlacement")
    for itype, vcpu, memgib, price, pergb, percpu, score in rows:
        avail = "?" if score is None else f"{score}"
        fam = itype.split(".", 1)[0]
        print(f"{itype},{fam},{vcpu},{memgib:.1f},{price:.4f},{pergb:.5f},{percpu:.5f},{avail}")


if __name__ == "__main__":
    main()
