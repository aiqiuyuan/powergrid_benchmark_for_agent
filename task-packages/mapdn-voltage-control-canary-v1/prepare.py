#!/usr/bin/env python3
"""Fetch only the pinned MAPDN 33-bus ZIP members into trusted storage.

Range extraction verifies each complete member's ZIP CRC32 and records SHA-256.
It does not claim to verify the SHA-256 of the un-downloaded 3.7 GB archive.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DATASET_COMMIT = "a41d8c269e402a827d36d9a153a4bce73a990e53"
ARCHIVE_SIZE = 3763536396
URL = (
    "https://huggingface.co/datasets/hsvgbkhgbv/"
    "Multi-Agent-Power-Distribution-Networks/resolve/"
    + DATASET_COMMIT
    + "/voltage_control_data.zip"
)
PREFIX = "voltage_control_data/case33_3min_final/"
MEMBERS = ("model.p", "pv_active.csv", "load_active.csv", "load_reactive.csv")


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def open_range(start: int, end: int):
    request = urllib.request.Request(
        URL + f"?range_start={start}", headers={"Range": f"bytes={start}-{end}"}
    )
    response = urllib.request.urlopen(request, timeout=120)
    expected = f"bytes {start}-{end}/{ARCHIVE_SIZE}"
    if response.status != 206 or response.headers.get("Content-Range") != expected:
        response.close()
        raise RuntimeError("server did not honor the exact requested archive range")
    return response


def entries() -> dict[str, dict]:
    start = ARCHIVE_SIZE - 65536
    with open_range(start, ARCHIVE_SIZE - 1) as response:
        tail = response.read()
    offset = tail.rfind(b"PK\x05\x06")
    if offset < 0:
        raise ValueError("ZIP end-of-directory record is missing")
    footer = struct.unpack_from("<4s4H2IH", tail, offset)
    if footer[1:3] != (0, 0) or footer[3] != footer[4]:
        raise ValueError("multi-disk archives are unsupported")
    cursor = footer[6] - start
    found = {}
    for _ in range(footer[4]):
        row = struct.unpack_from("<4s6H3I5H2I", tail, cursor)
        if row[0] != b"PK\x01\x02":
            raise ValueError("invalid ZIP central directory")
        name_len, extra_len, comment_len = row[10:13]
        name = tail[cursor + 46 : cursor + 46 + name_len].decode("utf-8")
        if name.startswith(PREFIX) and name[len(PREFIX) :] in MEMBERS:
            found[name[len(PREFIX) :]] = {
                "member": name,
                "method": row[4],
                "crc32": row[7],
                "compressed_size": row[8],
                "size": row[9],
                "offset": row[-1],
            }
        cursor += 46 + name_len + extra_len + comment_len
    if set(found) != set(MEMBERS):
        raise ValueError("the pinned archive lacks a required 33-bus member")
    return found


def extract_one(destination: Path, row: dict) -> dict:
    name = Path(row["member"]).name
    output = destination / name
    receipt = destination / (name + ".receipt.json")
    if receipt.exists() and output.exists():
        old = json.loads(receipt.read_text())
        if (
            old.get("dataset_commit") == DATASET_COMMIT
            and old.get("size") == output.stat().st_size
            and old.get("sha256") == sha256(output)
        ):
            return old
    with open_range(row["offset"], row["offset"] + 29) as response:
        header = struct.unpack("<4s5H3I2H", response.read())
    if header[0] != b"PK\x03\x04" or header[3] != row["method"] or row["method"] != 8:
        raise ValueError("unsupported or inconsistent ZIP local header")
    data_start = row["offset"] + 30 + header[-2] + header[-1]
    compressed = destination / (name + ".deflate")
    already = compressed.stat().st_size if compressed.exists() else 0
    if already > row["compressed_size"]:
        raise ValueError("cached compressed member exceeds expected size")
    while already < row["compressed_size"]:
        # Bounded ranges survive gateways which truncate very large responses.
        end = min(already + (16 << 20), row["compressed_size"])
        with open_range(data_start + already, data_start + end - 1) as response:
            with compressed.open("ab") as stream:
                while chunk := response.read(1 << 20):
                    stream.write(chunk)
        current = compressed.stat().st_size
        if current <= already:
            raise ValueError("empty range response; rerun preparation to resume")
        already = current
    if compressed.stat().st_size != row["compressed_size"]:
        raise ValueError("truncated compressed member; rerun preparation to resume")
    partial = destination / (name + ".partial")
    decompressor = zlib.decompressobj(-15)
    checksum, size, digest = 0, 0, hashlib.sha256()
    with compressed.open("rb") as source, partial.open("wb") as stream:
        while chunk := source.read(1 << 20):
            value = decompressor.decompress(chunk)
            stream.write(value)
            checksum = zlib.crc32(value, checksum)
            size += len(value)
            digest.update(value)
        value = decompressor.flush()
        stream.write(value)
        checksum = zlib.crc32(value, checksum)
        size += len(value)
        digest.update(value)
    if not decompressor.eof or size != row["size"] or checksum != row["crc32"]:
        raise ValueError("ZIP member failed decompression, size, or CRC32 verification")
    partial.replace(output)
    result = {
        **row,
        "sha256": digest.hexdigest(),
        "dataset_commit": DATASET_COMMIT,
        "verification": "complete-member-crc32-and-local-sha256; archive-sha256-not-verified",
    }
    receipt.write_text(json.dumps(result, indent=2) + "\n")
    compressed.unlink()
    print(f"verified {name}: {size} bytes", flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    catalog = entries()
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(lambda name: extract_one(args.output, catalog[name]), MEMBERS))
    (args.output / "preparation-receipt.json").write_text(
        json.dumps(
            {
                "dataset_commit": DATASET_COMMIT,
                "archive_size_bytes": ARCHIVE_SIZE,
                "archive_sha256_verified": False,
                "network": "case33_3min_final",
                "members": receipts,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
