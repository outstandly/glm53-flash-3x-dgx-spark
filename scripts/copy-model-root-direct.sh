#!/usr/bin/env bash
# Kopierar ~/jspark-models till Spark 3 över CX7 (<rank2 fabric ip>) med O_DIRECT-läsning (ingen page cache på Munin).
set -uo pipefail
SRC=$HOME/jspark-models; DST_HOST=<user>@<rank2 fabric ip>
ssh -o BatchMode=yes $DST_HOST "mkdir -p ~/jspark-models"
cd "$SRC"
find . -type d | ssh -o BatchMode=yes $DST_HOST "cd ~/jspark-models && xargs -I{} mkdir -p {}"
n=0; total=$(find . -type f | wc -l)
find . -type f | sort | while read -r f; do
  n=$((n+1)); sz=$(stat -c %s "$f")
  if [ "$sz" -gt 16777216 ]; then
    dd if="$f" iflag=direct bs=16M status=none | ssh -o BatchMode=yes -o Compression=no -c aes128-gcm@openssh.com $DST_HOST "cat > ~/jspark-models/$f"
  else
    scp -q -o BatchMode=yes "$f" "$DST_HOST:~/jspark-models/$f"
  fi
  echo "$(date +%H:%M:%S) $n/$total $f $((sz/1048576)) MB"
done
echo DONE
