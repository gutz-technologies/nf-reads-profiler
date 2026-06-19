#!/usr/bin/env python3
"""Graviton spot prices in a region, sorted by value ($/vCPU, $/GB).

Helps pick instance types for the Batch queues (e.g. spot-metaphlan). Lists every
in-region instance type in the requested families, pulls the cheapest current spot
price across AZs, joins in AWS's public Spot Advisor interruption-frequency data,
and ranks by value. Defaults to the Graviton4 r8g memory family.

  ./get_aws_spot_prices.py                       # r8g family, us-east-2, by $/vCPU
  ./get_aws_spot_prices.py -f r8g m8g c8g        # compare families
  ./get_aws_spot_prices.py --sort gb             # rank by $/GB instead
"""

import argparse
import json
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

DEFAULT_REGION = "us-east-2"
DEFAULT_FAMILIES = ["r8g", "r8gd", "r8gn", "r8gb", "r8gdb", "r8gdn"]
PRODUCT = "Linux/UNIX"
SPOT_ADVISOR_URL = "https://spot-bid-advisor.s3.amazonaws.com/spot-advisor-data.json"


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


def load_eviction_rates(region):
    """Public AWS Spot Advisor data: {instance_type: (interrupt_label, savings_pct)}.

    No auth, no AWS CLI call — same JSON backing the Spot Instance Advisor console
    page. Interruption is a coarse historical bucket (<5%, 5-10%, ... >20%), not a
    live probability, but it's the only signal AWS publishes per instance type.
    """
    try:
        with urllib.request.urlopen(SPOT_ADVISOR_URL, timeout=10) as resp:
            data = json.load(resp)
    except Exception as e:
        print(f"WARNING: spot advisor data unavailable ({e})", file=sys.stderr)
        return {}
    labels = {r["index"]: r["label"] for r in data["ranges"]}
    region_data = data.get("spot_advisor", {}).get(region, {}).get("Linux", {})
    return {
        itype: (labels.get(v["r"], "?"), v["s"])
        for itype, v in region_data.items()
    }


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
    args = ap.parse_args()

    families = None if args.all else args.families
    fam_label = "all Graviton" if args.all else " ".join(args.families)
    types = list_types(args.region, families)
    if not types:
        print(f"No in-region arm64 types found for: {fam_label}", file=sys.stderr)
        sys.exit(1)

    eviction = load_eviction_rates(args.region)

    rows = []
    with ThreadPoolExecutor(max_workers=16) as ex:
        prices = ex.map(lambda t: cheapest_spot(args.region, t[0]), types)
        for (itype, vcpu, memgib), price in zip(types, prices):
            if price is None:
                continue
            interrupt, savings = eviction.get(itype, ("?", None))
            rows.append((itype, vcpu, memgib, price, price / memgib, price / vcpu, interrupt, savings))

    sort_idx = {"price": 3, "gb": 4, "vcpu": 5}[args.sort]
    rows.sort(key=lambda r: r[sort_idx])

    print(f"# Graviton spot prices — {args.region} — families: {' '.join(args.families)} "
          f"(sorted by ${'/vCPU' if args.sort == 'vcpu' else '/GB' if args.sort == 'gb' else '/hr'})")
    print("TYPE,vCPU,MemGiB,Spot$/hr,$/GB,$/vCPU,Interrupt,Savings%")
    for itype, vcpu, memgib, price, pergb, percpu, interrupt, savings in rows:
        sav = f"{savings}" if savings is not None else "?"
        print(f"{itype},{vcpu},{memgib:.1f},{price:.4f},{pergb:.5f},{percpu:.5f},{interrupt},{sav}")


if __name__ == "__main__":
    main()
