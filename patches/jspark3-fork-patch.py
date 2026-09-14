#!/usr/bin/env python3
"""JONATHAN-FORK av jspark3 v1.1 (recipe/scripts/fleetctl.py), 2026-09-14.

1. Vision PÅ: tar bort --language-model-only och lägger Mias flaggor
   (--skip-mm-profiling + --limit-mm-per-prompt), samma image/mm-encoder-läge som FlyCockpits
   trenodskörning med bild på.
2. gpu-memory-utilization 0.83 -> 0.78: 0.83 lämnade bara 4-6 GB MemAvailable per nod
   (KV-poolen tog allt), samma läge som fällde Hugin 2026-09-11. Mias regel: huvudrum framför pool.

Körs i recipe/-katalogen. Uppdaterar SHA256SUMS-raden för fleetctl.py så clean-room-setup går igenom.
Idempotent: kör bara om markören saknas.
"""
import hashlib
import re
import sys
from pathlib import Path

recipe = Path.cwd()
fl = recipe / "scripts" / "fleetctl.py"
sums = recipe / "SHA256SUMS"
s = fl.read_text()

if "JONATHAN-FORK" in s:
    print("redan patchad")
else:
    old_argv = ('"--tool-call-parser", "glm47", "--enable-auto-tool-choice", "--reasoning-parser", "glm45",\n'
                '        "--language-model-only", "--mm-encoder-tp-mode", "data", "--enable-expert-parallel",')
    new_argv = ('"--tool-call-parser", "glm47", "--enable-auto-tool-choice", "--reasoning-parser", "glm45",\n'
                '        # JONATHAN-FORK 2026-09-14: vision på (Mias flaggor) i stället för --language-model-only\n'
                '        "--skip-mm-profiling", "--limit-mm-per-prompt", \'{"image":400,"video":1}\',\n'
                '        "--mm-encoder-tp-mode", "data", "--enable-expert-parallel",')
    if old_argv not in s:
        sys.exit("argv-blocket hittades inte – fleetctl.py har ändrats")
    s = s.replace(old_argv, new_argv)
    old_util = '"--gpu-memory-utilization", "0.83",'
    if old_util not in s:
        sys.exit("util-raden hittades inte")
    # OBS: util och max-model-len ligger på SAMMA rad i originalet – ingen kommentar mitt i raden.
    s = s.replace(old_util, '"--gpu-memory-utilization", "0.78",')
    backups = recipe.parent / "fork-backups"   # preflight vägrar extra filer inne i recipe/
    backups.mkdir(exist_ok=True)
    (backups / "fleetctl.py.orig").write_text(fl.read_text())
    fl.write_text(s)
    compile(s, str(fl), "exec")
    print("fleetctl.py patchad (backup fleetctl.py.orig)")

h = hashlib.sha256(fl.read_bytes()).hexdigest()
lines = sums.read_text().splitlines()
out = []
hit = False
for line in lines:
    m = re.match(r"^([0-9a-f]{64})(\s+\*?)(scripts/fleetctl\.py)$", line)
    if m:
        out.append(f"{h}{m.group(2)}{m.group(3)}"); hit = True
    else:
        out.append(line)
if not hit:
    sys.exit("scripts/fleetctl.py saknas i SHA256SUMS")
orig = recipe.parent / "fork-backups" / "SHA256SUMS.orig"
orig.parent.mkdir(exist_ok=True)
if not orig.exists():
    orig.write_text(sums.read_text())
sums.write_text("\n".join(out) + "\n")
print("SHA256SUMS uppdaterad:", h[:12])
