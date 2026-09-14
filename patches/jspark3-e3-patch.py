#!/usr/bin/env python3
"""JONATHAN-FORK step 2 (2026-09-14): MiaAI-Lab E3 grouped fat-expert MoE prefill on the jspark3 3-node stack.

What it does on ONE node (run it on every rank, controller included; idempotent):
  1. Replaces FlyCockpit's overlay/miaai/exl3.py with the merged file (Mia's current overlay/exl3.py, which
     carries the E2/E3 fat tiers, plus FlyCockpit's two TP3/EP load fixes). Backup kept outside recipe/.
  2. Updates the exl3.py source/after sha in scripts/_contracts.py and config/patch-contract.json.
  3. Recomputes the expected transform_target_set_sha256 in scripts/fleetctl.py (final target set changed).
  4. Adds the E3 env (EXL3_FAT_GROUPED=1, EXL3_TEMP_ROWS_FUSED=32, MAX_NUM_BATCHED_TOKENS=8192) and a
     read-only bind mount of ../e3/exl3_fat_moe_ext.so (built with Mia's build_exl3_fat_moe_ext.py inside the
     pinned image) into the container's dist-packages, in scripts/fleetctl.py.
  5. Rewrites the SHA256SUMS rows for the three recipe files.

Usage: jspark3-e3-patch.py /tmp/exl3_merged.py [--recipe ~/recipe-jspark3/recipe] [--fly ~/recipe-flycockpit-3x]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # clean-room refuses a scripts/__pycache__ inside recipe/

OLD_EXL3_SHA = "9e823926962d11c410b74a651c21e5b56c4751afa453cb62c637468da98cccb6"
OLD_TARGET_SET_SHA = "1f3beb88157da0a7782cc94d49bc5c8d93103fa708b620f8b3fb51f110a8f635"

ENV_ANCHOR = '        "GLM53_SUPPRESS_STOPS_IN_REASONING": "1", "GLM53_MIXED_PREFILL_CHUNK": "skip",\n'
ENV_INSERT = (
    "        # JONATHAN-FORK E3 2026-09-14: MiaAI-Lab grouped fat-expert MoE prefill (PR #132)\n"
    '        "EXL3_FAT_GROUPED": "1", "EXL3_TEMP_ROWS_FUSED": "32", "MAX_NUM_BATCHED_TOKENS": "8192",\n'
)
MOUNT_ANCHOR = '        "--mount", f"type=bind,src={work}/cache/tilelang,dst=/root/.tilelang/cache",\n'
MOUNT_INSERT = (
    "        # JONATHAN-FORK E3: additive exl3_fat_moe_ext module built in the pinned image\n"
    '        "--mount", f"type=bind,src={values[\'JSPARK_RECIPE_ROOT\'].rstrip(\'/\').rsplit(\'/\', 1)[0]}'
    '/e3/exl3_fat_moe_ext.so,dst=/usr/local/lib/python3.12/dist-packages/exl3_fat_moe_ext.so,readonly",\n'
)
# fleetctl verifies the created container's mounts against this table ("mount contract drift").
EXPECTED_ANCHOR = '        "/root/.tilelang/cache": (f"{work}/cache/tilelang", True),\n'
EXPECTED_INSERT = (
    "        # JONATHAN-FORK E3\n"
    '        "/usr/local/lib/python3.12/dist-packages/exl3_fat_moe_ext.so":\n'
    '            (f"{values[\'JSPARK_RECIPE_ROOT\'].rstrip(\'/\').rsplit(\'/\', 1)[0]}/e3/exl3_fat_moe_ext.so", False),\n'
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def backup(path: Path, backdir: Path, suffix: str) -> None:
    dest = backdir / (path.name + suffix)
    if not dest.exists():
        shutil.copy2(path, dest)
        print(f"  backup -> {dest}")


def replace_sha(path: Path, old: str, new: str, expect: int) -> None:
    text = path.read_text()
    n = text.count(old)
    if n == 0 and text.count(new) >= expect:
        print(f"  {path.name}: already updated")
        return
    if n != expect:
        raise SystemExit(f"{path}: expected {expect} occurrences of {old[:12]}, found {n}")
    path.write_text(text.replace(old, new))
    print(f"  {path.name}: {n} sha rows updated")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("merged", type=Path)
    ap.add_argument("--recipe", type=Path, default=Path.home() / "recipe-jspark3/recipe")
    ap.add_argument("--fly", type=Path, default=Path.home() / "recipe-flycockpit-3x")
    args = ap.parse_args()

    recipe, fly = args.recipe.resolve(), args.fly.resolve()
    backdir = recipe.parent / "fork-backups"
    backdir.mkdir(exist_ok=True)
    merged = args.merged.read_bytes()
    new_sha = hashlib.sha256(merged).hexdigest()
    compile(merged, "exl3.py", "exec")
    for seam, count in (("_exl3_expert_map_device", 2), ("def _maybe_shard(", 1)):
        if merged.decode().count(seam) != count:
            raise SystemExit(f"merged exl3.py: seam {seam!r} count != {count}")
    print(f"merged exl3.py sha256 {new_sha}")

    # 1. Fly overlay
    fly_exl3 = fly / "overlay/miaai/exl3.py"
    cur = sha(fly_exl3)
    if cur == OLD_EXL3_SHA:
        backup(fly_exl3, backdir, ".fly.orig")
        fly_exl3.write_bytes(merged)
        print("  fly overlay/miaai/exl3.py replaced")
    elif cur == new_sha:
        print("  fly overlay/miaai/exl3.py already merged")
    else:
        raise SystemExit(f"fly exl3.py has unexpected sha {cur}")

    # 2. Contract copies
    contracts_py = recipe / "scripts/_contracts.py"
    contract_json = recipe / "config/patch-contract.json"
    fleetctl = recipe / "scripts/fleetctl.py"
    for p in (contracts_py, contract_json, fleetctl):
        backup(p, backdir, ".pre-e3")
    replace_sha(contracts_py, OLD_EXL3_SHA, new_sha, 3)
    replace_sha(contract_json, OLD_EXL3_SHA, new_sha, 3)

    # 2b. Cadence B5 prefix-verify module pins the image exl3.py sha too (hash gate at first import),
    #     and the module itself is pinned in fleetctl.py (B45_MODULES) and config/cadence-contract.json.
    b5 = recipe / "modules/b5_prefix_verify.py"
    cadence = recipe / "config/cadence-contract.json"
    for p in (b5, cadence):
        backup(p, backdir, ".pre-e3")
    b5_old_sha = sha(b5)
    replace_sha(b5, OLD_EXL3_SHA, new_sha, 1)
    b5_new_sha = sha(b5)
    if b5_new_sha != b5_old_sha:
        replace_sha(cadence, b5_old_sha, b5_new_sha, 1)
    print(f"  b5_prefix_verify.py sha256 {b5_new_sha}")

    # 3. Recompute the final target-set sha exactly as apply_base_pipeline does
    sys.path.insert(0, str(recipe / "scripts"))
    for mod in ("apply_base_pipeline", "_contracts"):
        sys.modules.pop(mod, None)
    abp = importlib.import_module("apply_base_pipeline")
    contracts = importlib.import_module("_contracts")
    whole = json.loads(contract_json.read_text(encoding="utf-8"))
    for name, section in contracts.SECTIONS.items():
        if whole["transforms"][name] != section:
            raise SystemExit(f"_contracts.py and patch-contract.json disagree on {name}")
    states, _records = abp.snapshots(whole)
    new_target_set = hashlib.sha256(abp.canonical(states[-1])).hexdigest()
    print(f"  transform_target_set_sha256 -> {new_target_set}")

    # 4. fleetctl.py: expected target set, env, mount
    text = fleetctl.read_text()
    if b5_new_sha != b5_old_sha:
        if text.count(b5_old_sha) != 1:
            raise SystemExit("fleetctl.py: B45_MODULES b5_prefix_verify.py sha not found")
        text = text.replace(b5_old_sha, b5_new_sha)
    elif b5_new_sha not in text:
        raise SystemExit("fleetctl.py: B45_MODULES b5_prefix_verify.py sha drift")
    if OLD_TARGET_SET_SHA in text:
        text = text.replace(OLD_TARGET_SET_SHA, new_target_set)
    elif new_target_set not in text:
        raise SystemExit("fleetctl.py: neither old nor new transform_target_set_sha256 present")
    if "EXL3_FAT_GROUPED" not in text:
        if text.count(ENV_ANCHOR) != 1:
            raise SystemExit("fleetctl.py: env anchor not found")
        text = text.replace(ENV_ANCHOR, ENV_ANCHOR + ENV_INSERT)
    if "exl3_fat_moe_ext.so,readonly" not in text:
        if text.count(MOUNT_ANCHOR) != 1:
            raise SystemExit("fleetctl.py: mount anchor not found")
        text = text.replace(MOUNT_ANCHOR, MOUNT_ANCHOR + MOUNT_INSERT)
    if '"/usr/local/lib/python3.12/dist-packages/exl3_fat_moe_ext.so":' not in text:
        if text.count(EXPECTED_ANCHOR) != 1:
            raise SystemExit("fleetctl.py: expected_mounts anchor not found")
        text = text.replace(EXPECTED_ANCHOR, EXPECTED_ANCHOR + EXPECTED_INSERT)
    fleetctl.write_text(text)
    compile(text, "fleetctl.py", "exec")
    print("  fleetctl.py: env + mount + expected target set in place")

    # 5. SHA256SUMS
    sums = recipe / "SHA256SUMS"
    rows = sums.read_text().splitlines()
    wanted = {"scripts/fleetctl.py": sha(fleetctl), "scripts/_contracts.py": sha(contracts_py),
              "config/patch-contract.json": sha(contract_json),
              "modules/b5_prefix_verify.py": sha(b5), "config/cadence-contract.json": sha(cadence)}
    out, seen = [], set()
    for row in rows:
        parts = row.split("  ", 1)
        if len(parts) == 2 and parts[1] in wanted:
            out.append(f"{wanted[parts[1]]}  {parts[1]}")
            seen.add(parts[1])
        else:
            out.append(row)
    if seen != set(wanted):
        raise SystemExit(f"SHA256SUMS rows missing: {set(wanted) - seen}")
    sums.write_text("\n".join(out) + "\n")
    print(f"  SHA256SUMS rewritten; manifest sha256 {sha(sums)}")
    so = recipe.parent / "e3/exl3_fat_moe_ext.so"
    print(f"  E3 module: {so} {'present ' + sha(so)[:16] if so.is_file() else 'MISSING'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
