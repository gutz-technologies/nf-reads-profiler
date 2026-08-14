#!/usr/bin/env python3
"""Emit the first N records of a gzipped FASTQ read from stdin, gzipped, on stdout.

Used by preprocess_gemma.nf for the `over32m` batch, where each lane contributes
only its proportional share of the 32M-pair cap. R1 and R2 are cut at the same
record count, which is all the positional correspondence fastp needs.

Two details that matter:

* gzip members concatenate natively, so a lane file may be a multi-member
  stream; the decompressor is restarted at every member boundary.
* After the quota is met we keep reading raw stdin to EOF instead of exiting.
  Exiting would SIGPIPE the upstream `aws s3 cp`, and a killed downloader is
  indistinguishable from a short read -- draining keeps `set -o pipefail`
  meaningful. Draining costs network, not CPU: the remainder is never
  decompressed.
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
    ap.add_argument("--level", type=int, default=1,
                    help="gzip level for the output stream (default 1: this is "
                         "an intermediate that fastp reads once)")
    ap.add_argument("--stats", help="write 'records_out<TAB>bytes_in' here")
    args = ap.parse_args()

    limit_lines = args.records * 4
    inp = sys.stdin.buffer
    out = gzip.GzipFile(fileobj=sys.stdout.buffer, mode="wb",
                        compresslevel=args.level, mtime=0)

    dec = zlib.decompressobj(47)  # 47 = auto-detect zlib/gzip header
    lines = 0
    bytes_in = 0
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

            n = data.count(b"\n")
            if lines + n < limit_lines:
                out.write(data)
                lines += n
                continue

            # cut exactly at the (limit_lines)-th newline
            need = limit_lines - lines
            idx = -1
            for _ in range(need):
                idx = data.index(b"\n", idx + 1)
            out.write(data[:idx + 1])
            lines = limit_lines
            done = True
            chunk = b""

    out.close()

    if args.stats:
        with open(args.stats, "w") as fh:
            fh.write("%d\t%d\n" % (lines // 4, bytes_in))


if __name__ == "__main__":
    main()
