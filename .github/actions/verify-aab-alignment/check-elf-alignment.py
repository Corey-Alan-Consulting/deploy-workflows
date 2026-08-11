#!/usr/bin/env python3
"""Verify every arm64 .so in an APK/AAB has 16KB-aligned LOAD segments.

Google Play hard gate (Nov 2025) for targetSdk 35+: 64-bit native libraries
must support 16KB page sizes. Usage: check-elf-alignment.py <bundle.aab|apk>
Exits non-zero listing any misaligned library.
"""

import struct
import sys
import zipfile

REQUIRED_ALIGNMENT = 16384


def load_alignments(data: bytes):
    if data[:4] != b"\x7fELF":
        return None
    is64 = data[4] == 2
    little = data[5] == 1
    if not is64:
        return []  # 32-bit ABIs are exempt from the 16KB requirement.
    endian = "<" if little else ">"
    e_phoff = struct.unpack(f"{endian}Q", data[32:40])[0]
    e_phentsize = struct.unpack(f"{endian}H", data[54:56])[0]
    e_phnum = struct.unpack(f"{endian}H", data[56:58])[0]
    alignments = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type = struct.unpack(f"{endian}I", data[off : off + 4])[0]
        if p_type == 1:  # PT_LOAD
            p_align = struct.unpack(f"{endian}Q", data[off + 48 : off + 56])[0]
            alignments.append(p_align)
    return alignments


def main(path: str) -> int:
    bad = []
    checked = 0
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if not name.endswith(".so") or "arm64-v8a" not in name:
                continue
            aligns = load_alignments(zf.read(name))
            if aligns is None:
                continue
            checked += 1
            if any(a < REQUIRED_ALIGNMENT for a in aligns):
                bad.append((name, aligns))
    if checked == 0:
        print("ERROR: no arm64-v8a .so files found — wrong artifact?")
        return 2
    for name, aligns in bad:
        print(f"MISALIGNED: {name} LOAD aligns={aligns}")
    print(f"checked {checked} arm64 libraries, {len(bad)} misaligned")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
