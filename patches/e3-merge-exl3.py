#!/usr/bin/env python3
"""Build /tmp/exl3_merged.py = MiaAI-Lab overlay/exl3.py (E2/E3 fat tiers) + FlyCockpit TP3/EP load fixes."""
import hashlib, re, sys
from pathlib import Path

src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "recipe-glm53-exl3-new/overlay/exl3.py"
s = src.read_text()

# Hunk 1 (FlyCockpit): pin the device expert map on the layer without re-assigning layer.expert_map.
old1 = (
    "    if emap.device != device or emap.dtype != torch.long:\n"
    "        layer.expert_map = emap.to(device=device, dtype=torch.long)\n"
    "    return layer.expert_map\n"
)
new1 = (
    '    pinned = getattr(layer, "_exl3_expert_map_device", None)\n'
    "    if pinned is None or pinned.device != device or pinned.dtype != torch.long:\n"
    "        pinned = emap.to(device=device, dtype=torch.long)\n"
    '        object.__setattr__(layer, "_exl3_expert_map_device", pinned)\n'
    "    return pinned\n"
)
# Hunk 2 (FlyCockpit): under expert parallel the destination already holds the full intermediate; do not TP-narrow.
old2 = (
    '        if shard_id in ("w1", "w3"):\n'
    '            shard_idx = 0 if shard_id == "w1" else 1\n'
    "            sharded = shard_exl3_col(loaded, suffix, tp_rank, tp_size)\n"
    "            dest = param.data[expert_id, shard_idx]\n"
    '        elif shard_id == "w2":\n'
    "            sharded = shard_exl3_row(loaded, suffix, tp_rank, tp_size)\n"
    "            dest = param.data[expert_id]\n"
)
new2 = (
    "        # JONATHAN-FORK (FlyCockpit TP3/EP): dest already has the full intermediate\n"
    "        # (2048) under expert parallel. Do not TP-narrow. TP-only: dest is 2048/tp\n"
    "        # and _narrow_tp applies.\n"
    "        def _maybe_shard(fn, dest):\n"
    "            if tuple(dest.shape) == tuple(loaded.shape):\n"
    "                return loaded\n"
    "            return fn(loaded, suffix, tp_rank, tp_size)\n"
    "\n"
    '        if shard_id in ("w1", "w3"):\n'
    '            shard_idx = 0 if shard_id == "w1" else 1\n'
    "            dest = param.data[expert_id, shard_idx]\n"
    "            sharded = _maybe_shard(shard_exl3_col, dest)\n"
    '        elif shard_id == "w2":\n'
    "            dest = param.data[expert_id]\n"
    "            sharded = _maybe_shard(shard_exl3_row, dest)\n"
)
assert s.count(old1) == 1, s.count(old1)
assert s.count(old2) == 1, s.count(old2)
merged = s.replace(old1, new1).replace(old2, new2)
compile(merged, "exl3_merged.py", "exec")
for seam in ("_exl3_expert_map_device", "def _maybe_shard("):
    assert seam in merged, seam
out = Path("/tmp/exl3_merged.py")
out.write_text(merged)
print("merged", len(merged), "bytes sha256", hashlib.sha256(merged.encode()).hexdigest())
