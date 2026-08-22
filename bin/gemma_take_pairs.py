#!/usr/bin/env python3
"""Subsample a gzipped FASTQ read from stdin down to N records, gzipped, on stdout.

Used by preprocess_gemma.nf when a sample is over the depth cap: each lane
contributes its proportional share of the cap, and this script takes that share
out of the lane. R1 and R2 are cut at the same record COUNT and, in systematic
mode, at the same record INDICES -- selection depends only on the record number,
never on content -- which is all the positional correspondence fastp needs.

Two selection modes:

* systematic (--total given, the default in the workflow) -- Bresenham stride
  over the whole lane: record i is emitted when the running accumulator
  `acc += records` crosses `total`. That spreads the kept reads evenly across
  the file, so no region of the flowcell is over- or under-represented. Requires
  decompressing the ENTIRE lane, which is the price of not biasing the sample.
  `--total` is the expected record count for the lane (the manifest's
  byte-derived estimate, +/-4%); the stride is computed from it, and the output
  is hard-capped at `--records`, so an estimate that runs high simply yields
  slightly fewer reads and one that runs low truncates the last few percent.

* head (--total omitted) -- emit the first N records and stop decompressing.
  Cheap, but it is TRUNCATION: on a flowcell-ordered file it samples one end of
  the tile range. Kept only for the smoke slice and for callers that genuinely
  want a prefix.

Two details that matter in both modes:

* gzip members concatenate natively, so a lane file may be a multi-member
  stream; the decompressor is restarted at every member boundary.
* stdin is always drained to EOF instead of exiting early. Exiting would
  SIGPIPE the upstream `aws s3 cp`, and a killed downloader is
  indistinguishable from a short read -- draining keeps `set -o pipefail`
  meaningful. In head mode the drain costs network, not CPU: the remainder is
  never decompressed.
"""

import argparse
import gzip
import sys
import zlib

CHUNK = 1 << 20


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--records", type=int, required=True,
                    help="number of FASTQ records (reads) to emit")
    ap.add_argument("--total", type=int, default=0,
                    help="expected records in this lane; enables systematic "
                         "(evenly-spread) selection instead of head truncation")
    ap.add_argument("--level", type=int, default=1,
                    help="gzip level for the output stream (default 1: this is "
                         "an intermediate that fastp reads once)")
    ap.add_argument("--stats", help="write 'records_out<TAB>bytes_in<TAB>records_in' here")
    args = ap.parse_args()

    keep = args.records
    total = args.total
    # A stride of >=1 keeps everything, so fall back to a straight copy rather
    # than paying the per-record loop for a no-op.
    systematic = total > 0 and keep < total

    inp = sys.stdin.buffer
    out = gzip.GzipFile(fileobj=sys.stdout.buffer, mode="wb",
                        compresslevel=args.level, mtime=0)

    dec = zlib.decompressobj(47)  # 47 = auto-detect zlib/gzip header
    bytes_in = 0
    records_in = 0
    records_out = 0
    lines = 0                     # head mode only
    limit_lines = keep * 4        # head mode only
    acc = 0                       # systematic mode: Bresenham accumulator
    carry = []                    # systematic mode: lines of a partial record
    leftover = b""                # bytes after the last newline of a chunk
    done = False

    while True:
        chunk = inp.read(CHUNK)
        if not chunk:
            break
        bytes_in += len(chunk)
        if done:
            continue  # drain only

        while chunk:
            try:
                data = dec.decompress(chunk)
            except zlib.error:
                # trailing padding after the final member -- nothing left to read
                chunk = b""
                done = True
                break

            if dec.eof:
                chunk = dec.unused_data
                dec = zlib.decompressobj(47)
                if chunk and not chunk.strip(b"\x00"):
                    chunk = b""
            else:
                chunk = b""

            if not data:
                continue

            if not systematic:
                # ---- head mode: bulk-copy until the record limit ----
                n = data.count(b"\n")
                if lines + n < limit_lines:
                    out.write(data)
                    lines += n
                    continue
                need = limit_lines - lines
                idx = -1
                for _ in range(need):
                    idx = data.index(b"\n", idx + 1)
                out.write(data[:idx + 1])
                lines = limit_lines
                records_out = keep
                records_in = keep
                done = True
                chunk = b""
                continue

            # ---- systematic mode: decide per record ----
            buf = leftover + data
            nl = buf.rfind(b"\n")
            if nl < 0:
                leftover = buf
                continue
            leftover = buf[nl + 1:]
            split = buf[:nl].split(b"\n")

            if carry:
                split = carry + split
                carry = []
            extra = len(split) % 4
            if extra:
                carry = split[len(split) - extra:]
                split = split[:len(split) - extra]

            it = iter(split)
            emit = []
            for rec in zip(it, it, it, it):
                records_in += 1
                acc += keep
                if acc >= total:
                    acc -= total
                    emit.append(b"\n".join(rec))
                    records_out += 1
                    if records_out >= keep:
                        break
            if emit:
                out.write(b"\n".join(emit))
                out.write(b"\n")
            if records_out >= keep:
                done = True
                chunk = b""

    # A final record with no trailing newline can only be sitting in leftover.
    if systematic and not done and leftover:
        rec = (carry + [leftover]) if carry else [leftover]
        if len(rec) == 4:
            records_in += 1
            acc += keep
            if acc >= total and records_out < keep:
                out.write(b"\n".join(rec))
                out.write(b"\n")
                records_out += 1

    out.close()

    if not systematic and not done:
        # head mode that never hit its limit: the lane was shorter than asked for
        records_out = lines // 4
        records_in = records_out

    if args.stats:
        with open(args.stats, "w") as fh:
            fh.write("%d\t%d\t%d\n" % (records_out, bytes_in, records_in))


if __name__ == "__main__":
    main()
