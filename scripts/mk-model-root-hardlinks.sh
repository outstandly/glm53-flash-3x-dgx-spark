#!/usr/bin/env bash
# Skapar jspark3:s modellrot med HÅRDLÄNKAR till HF-cachens blobs (regular files, noll extra disk).
set -euo pipefail
HUB="$1"; ROOT=$HOME/jspark-models
T_SRC="$HUB/models--brandonmusic--GLM-5.3-Flash-tr3-4bpw/snapshots/5ab363a8dcf6405955fd5f99671e01a1c9fb124b"
D_SRC="$HUB/models--incoai--GLM-5.3-Flash-DFlash2/snapshots/dc77ff1c99eeb2df044ee3d4f0094eb033fee410"
T_DST="$ROOT/Mia-AiLab--GLM-5.3-Flash-EXL3-TR3-4bpw-25a44fdb"
D_DST="$ROOT/incoai--GLM-5.3-Flash-DFlash2-dc77ff1c-native"
link_tree() { # src dst
  local src="$1" dst="$2"; mkdir -p "$dst"
  (cd "$src" && find . -type d) | while read -r d; do mkdir -p "$dst/$d"; done
  (cd "$src" && find . -type f -o -type l) | while read -r f; do
    real=$(readlink -f "$src/$f"); [ -f "$real" ] || { echo "saknas: $f" >&2; continue; }
    [ -e "$dst/$f" ] || ln "$real" "$dst/$f" 2>/dev/null || cp "$real" "$dst/$f"
  done
}
link_tree "$T_SRC" "$T_DST"; link_tree "$D_SRC" "$D_DST"
echo "target: $(find "$T_DST" -name '*.safetensors' | wc -l) shards, $(du -sh --apparent-size "$T_DST" | cut -f1) (disk: $(du -sh "$T_DST" | cut -f1))"
echo "draft:  $(ls "$D_DST" | tr '\n' ' ')"
find "$T_DST" "$D_DST" -type l | wc -l | sed 's/^/symlänkar kvar: /'
