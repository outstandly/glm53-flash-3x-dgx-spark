#!/usr/bin/env python3
"""Cold-prefill benchmark: unique random prompts (defeats prefix cache), max_tokens=1.
Reports prompt tokens / wall time = prefill tok/s."""
import json, os, random, sys, time, urllib.request

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/v1/chat/completions"
SIZES = [int(s) for s in (sys.argv[2].split(",") if len(sys.argv) > 2 else ["8000", "32000", "100000"])]
REPS = int(sys.argv[3]) if len(sys.argv) > 3 else 2
MODEL = os.environ.get("MODEL", "glm-5.3-flash")
KEY = os.environ.get("KEY", "")
WORDS = ("alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa "
         "quebec romeo sierra tango uniform victor whiskey xray yankee zulu server kernel tensor spark node "
         "matrix vector gradient token layer expert router cache block page memory fabric ring switch").split()

def prompt(n_tokens, seed):
    rnd = random.Random(seed)
    lines = []
    # ~1.15 tokens per word here; over-generate slightly and let the server count.
    for i in range(int(n_tokens / 1.15 / 12) + 1):
        lines.append(f"{i:06d}: " + " ".join(rnd.choice(WORDS) for _ in range(12)))
    return "Read the log below and answer with one word: which word appears first on line 000003?\n\n" + "\n".join(lines)

for n in SIZES:
    for r in range(REPS):
        body = json.dumps({"model": MODEL, "messages": [{"role": "user", "content": prompt(n, time.time_ns() + r)}],
                           "max_tokens": 1, "temperature": 0}).encode()
        req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + KEY} if KEY else {})})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=1800) as resp:
                out = json.loads(resp.read())
            dt = time.time() - t0
            pt = out["usage"]["prompt_tokens"]
            print(f"target={n:>7} prompt_tokens={pt:>7} wall={dt:7.2f}s prefill={pt/dt:8.1f} tok/s", flush=True)
        except Exception as e:
            print(f"target={n} rep={r} ERROR {type(e).__name__}: {str(e)[:200]}", flush=True)
