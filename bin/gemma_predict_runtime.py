#!/usr/bin/env python3
"""Predict profile_taxa/profile_function runtime for the GEMMA cohorts from
read-count estimates, using linear models fit by gemma_runtime_vs_readcount.R.

Sources:
  - per-sample est_read_pairs: gemma_sample_summary.tsv (globus_2026 transfer manifest)
  - batch membership (under8g/over8g): gemma_manifest_{under8g,over8g}.tsv 'run' column
  - actual runtime (under8g only, for error-checking): gemma_readcount_runtime.tsv
    from gemma_join_readcount_runtime.py

Model coefficients are passed on the CLI (not re-fit here) so this stays a
pure prediction/reporting step separate from the R fitting step.
"""

import argparse
import csv


def load_batch_membership(paths):
    membership = {}
    for batch, path in paths.items():
        with open(path) as f:
            for row in csv.DictReader(f, delimiter="\t"):
                membership[row["sample_id"]] = batch
    return membership


def load_est_reads(path):
    est = {}
    with open(path) as f:
        for row in csv.DictReader(f, delimiter="\t"):
            est[row["sample_id"]] = int(row["est_read_pairs"])
    return est


def load_actual(path):
    actual = {}
    with open(path) as f:
        for row in csv.DictReader(f, delimiter="\t"):
            pt = float(row["profile_taxa_min"]) if row["profile_taxa_min"] else None
            pf = float(row["profile_function_min"]) if row["profile_function_min"] else None
            actual[row["sample"]] = (int(row["readcount"]), pt, pf)
    return actual


def predict(readcount, intercept, slope):
    return intercept + slope * readcount


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest-under8g", required=True)
    ap.add_argument("--manifest-over8g", required=True)
    ap.add_argument("--sample-summary", required=True, help="gemma_sample_summary.tsv (est_read_pairs)")
    ap.add_argument("--actual-under8g", required=True, help="gemma_readcount_runtime.tsv (actual runtimes)")
    ap.add_argument("--taxa-intercept", type=float, default=2.259)
    ap.add_argument("--taxa-slope", type=float, default=3.095e-07)
    ap.add_argument("--function-intercept", type=float, default=6.425)
    ap.add_argument("--function-slope", type=float, default=3.026e-06)
    args = ap.parse_args()

    membership = load_batch_membership({
        "under8g": args.manifest_under8g,
        "over8g": args.manifest_over8g,
    })
    est_reads = load_est_reads(args.sample_summary)
    actual = load_actual(args.actual_under8g)

    for batch in ("under8g", "over8g"):
        samples = [s for s, b in membership.items() if b == batch]
        print(f"\n=== {batch} (n={len(samples)}) ===")

        pred_taxa_total = pred_func_total = 0.0
        n_est = 0
        for s in samples:
            rc = est_reads.get(s)
            if rc is None:
                continue
            n_est += 1
            pred_taxa_total += predict(rc, args.taxa_intercept, args.taxa_slope)
            pred_func_total += predict(rc, args.function_intercept, args.function_slope)

        print(f"samples with read-count estimate: {n_est}/{len(samples)}")
        print(f"predicted profile_taxa total: {pred_taxa_total:.1f} min ({pred_taxa_total/60:.1f} h)")
        print(f"predicted profile_function total: {pred_func_total:.1f} min ({pred_func_total/60:.1f} h)")
        print(f"predicted combined total: {(pred_taxa_total+pred_func_total):.1f} min "
              f"({(pred_taxa_total+pred_func_total)/60:.1f} h)")

        if batch == "under8g":
            errs_taxa, errs_func = [], []
            for s in samples:
                rc_est = est_reads.get(s)
                if rc_est is None or s not in actual:
                    continue
                rc_actual, pt_actual, pf_actual = actual[s]
                if pt_actual is not None:
                    pt_pred = predict(rc_est, args.taxa_intercept, args.taxa_slope)
                    errs_taxa.append((pt_pred - pt_actual) / pt_actual)
                if pf_actual is not None:
                    pf_pred = predict(rc_est, args.function_intercept, args.function_slope)
                    errs_func.append((pf_pred - pf_actual) / pf_actual)

            def summarize(errs, label):
                if not errs:
                    print(f"{label}: no comparable samples")
                    return
                mae = sum(abs(e) for e in errs) / len(errs)
                mean = sum(errs) / len(errs)
                print(f"{label}: n={len(errs)}  mean signed error={mean*100:+.2f}%  "
                      f"mean abs error={mae*100:.2f}%")

            print("-- estimate error vs actual runtime --")
            summarize(errs_taxa, "profile_taxa")
            summarize(errs_func, "profile_function")


if __name__ == "__main__":
    main()
