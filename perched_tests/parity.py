"""
Parity contract (null effect): with no SOIL2, VG or STRUCT line, swmm524-perched
must write the same .out bytes (and the same LID report) as EPA SWMM 5.2.4.

This is the "parity" group of verify.py: 930 inputs generated fresh (896 recovery,
28 season, 6 eight-inch storm).  It fails, with exit status 1, on zero cases, a
count that differs from tests_manifest.json, an engine that exits non-zero or
writes no .out, or any byte difference.

    python3 parity.py            # same as: python3 verify.py --only parity
"""
import sys
import verify

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "--only", "parity"] + sys.argv[1:]
    sys.exit(verify.main())
