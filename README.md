# GLM-5.3-Flash on 3× NVIDIA DGX Spark — with vision, 1M context and real memory headroom

A field-tested setup for running **GLM-5.3-Flash (EXL3 4 bpw)** across three DGX Spark (GB10) nodes,
based on [jakejharris/jspark3](https://github.com/jakejharris/jspark3) v1.1 (which builds on
[FlyCockpit's TP3/EP3 work](https://github.com/FlyCockpit/GLM-5.3-Flash-EXL3-3x-DGX-Sparks) and the
[MiaAI-Lab](https://github.com/MiaAI-Lab/GLM-5.3-Flash-EXL3-2x-DGX-Sparks) engine image), plus a small
fork that:

1. **turns image input back on** (jspark3 ships text-only), using the same flags MiaAI-Lab uses on two nodes;
2. **lowers `gpu-memory-utilization` from 0.83 to 0.78**, because 0.83 left only 4–6 GB of host memory per
   node — the same margin that swapped and crashed a node for us on two nodes;
3. documents every trap we hit getting a *switchless triangle* of Sparks to boot, so it takes you 30 minutes
   instead of an evening.

Nothing here modifies weights, drafter or the engine image. The fork is one launcher file (`fleetctl.py`)
and a recomputed checksum line.

## Measured (2026-09-14, same three boxes, temperature 0, 400-token generations, median of 3)

| | 2× Spark (MiaAI-Lab TP2) | **3× Spark (this setup)** |
|---|---:|---:|
| Decode, structured output | 73 tok/s | **95 tok/s** |
| Decode, code | 45 tok/s | **51–56 tok/s** |
| Decode, prose | 33 tok/s | **41 tok/s** |
| TTFT, short prompt | 0.33 s | 0.25–0.30 s |
| 1 / 2 / 3 concurrent code streams (aggregate) | – | 88 / 146 / 195 tok/s |
| Per stream at 3 concurrent | – | 66 tok/s |
| Max context | 850k | **1M** |
| KV pool | ~880k tokens | ~1.8M tokens |
| Free host memory per node while serving | 4–6 GB | **9–12 GB** |
| Image input | yes | **yes** |
| Long-prompt prefill | ~1,580 tok/s (Mia's E3 kernels) | ~1,230 tok/s (E3 not ported yet) |
| Cold boot → healthy | ~10 min | 13–18 min |

Same weights, same answers. What the third node buys is +20–30 % single-stream decode, near-linear
scaling to three concurrent users, double the memory headroom and 1M context. The one regression is
long-prompt prefill; porting Mia's E3 fused-MoE kernels is the obvious next step.

## What you need

- **3× DGX Spark** (or ASUS Ascent GX10 — same GB10 board), 128 GB each. Check
  `sudo lspci -vv | grep -A2 ConnectX` shows `Speed 32GT/s, Width x4` on all four ConnectX functions.
- **Three QSFP DAC cables, wired as a directed ring**: each node's *Port0* (the cage next to the RJ45)
  to the next node's *Port1*. Our ring: head f0 → worker-2 f1, worker-2 f0 → worker-1 f1, worker-1 f0 → head f1.
  One /24 per cable, **MTU 9000**, `ipv4.never-default yes`, as persistent NetworkManager profiles.
- **RoCE v2 IPv4 GID at the same index (3) on all six ports.** Disable IPv6 on the fabric profiles, or the
  index drifts. Check: `cat /sys/class/infiniband/rocep1s0f{0,1}/ports/1/gids/3` on every node.
- **Why the ring direction matters:** NCCL pairs NIC index to NIC index per channel, and
  `NCCL_IB_SUBNET_AWARE_ROUTING=1` can only correct a pair when *one* side already points at the right
  peer. With two nodes using the same port index towards the third, that pair can never connect
  (`ibv_modify_qp … Connection timed out`, then `NCCL error: unhandled system error`). The directed ring
  above satisfies the rule; a "mirrored" ring does not. Reordering `NCCL_IB_HCA` does **not** help — NCCL
  enumerates devices in system order.
- **Remove the CX7 hotplug trigger on all nodes** before you ever reboot one of them:
  `sudo mv /etc/nvidia/cx7-hotplug-enabled /root/cx7-hotplug-enabled.backup` (credit:
  [NNNtrance](https://github.com/NNNtrance/GLM-5.3-Flash-EXL3-DGX-Spark) docs/00 §3 and
  digchick/dgx-spark-200g-link-fix). Otherwise a rebooting node removes a ConnectX port from its
  *neighbour's* PCI bus. Reboot all three together, never one.
- A management network reachable from all nodes (we use Tailscale; `tailscale0` is the socket interface).
- ~180 GB free per node for the target checkpoint, plus ~21 GB for the image.
- Licences: the target checkpoint is under the ShapleyMcg License v1.0 (attribution required), the DFlash2
  drafter is CC BY-NC-ND 4.0 (non-commercial). Read `LICENSES.md`/`LICENSING.md` in jspark3 before serving.

## Steps

All paths must be **identical on every node**. We use `/home/<user>/…`; jspark3's docs use `/srv/…`.

1. **Clone the pinned sources on every node**
   ```bash
   git clone https://github.com/jakejharris/jspark3 ~/recipe-jspark3          # we used 7021055
   git clone https://github.com/FlyCockpit/GLM-5.3-Flash-EXL3-3x-DGX-Sparks ~/recipe-flycockpit-3x
   git -C ~/recipe-flycockpit-3x checkout 9093765c757bd1976372196e44af84a67cf86bad
   docker pull ghcr.io/miaai-lab/glm-5.3-flash-2x-dgx-sparks@sha256:9bb1557a4234fce63d59599e44d10747eabd742beb337eebf9e7070be8a0fd58
   ```
2. **Checkpoints.** If you already run MiaAI-Lab's two-node recipe you have both the target
   (`brandonmusic/GLM-5.3-Flash-tr3-4bpw@5ab363a8`, byte-identical to the pinned
   `Mia-AiLab/GLM-5.3-Flash-EXL3-TR3-4bpw@25a44fdb`) and the drafter (`incoai/GLM-5.3-Flash-DFlash2@dc77ff1c`)
   in a Hugging Face cache. jspark3's validator refuses symlinks, so build the model root with **hard links**
   (zero extra disk): `scripts/mk-model-root-hardlinks.sh <hf-hub-dir>`. Copy it to the node that lacks it
   with `scripts/copy-model-root-direct.sh` (O_DIRECT reads, so the copy does not evict a serving node's
   page cache). Otherwise download as in jspark3's `docs/INSTALL.md` §3.
3. **Validator trap #1:** the pinned publication *omits* `.materialization/shards/*.safetensors.json` and the
   `runtime/` directory, and the validator requires exactly those to be **absent**. If your copy came from
   the brandonmusic tree, delete them from the model root:
   ```bash
   T=~/jspark-models/Mia-AiLab--GLM-5.3-Flash-EXL3-TR3-4bpw-25a44fdb
   rm -f "$T"/.materialization/shards/model-*-of-00120.safetensors.json; rm -rf "$T/runtime"
   ```
4. **Runtime views and validation, on every node** (jspark3 `docs/INSTALL.md` §4). **Trap #2:** create the
   runtime views *after* step 3, or the view inventory drifts and validation refuses.
5. **Fabric:** MTU 9000 on all six ports (`nmcli con mod <profile> 802-3-ethernet.mtu 9000 && nmcli con up <profile>`),
   verify with `ping -M do -s 8972 <peer>` across every leg. GID index 3 everywhere. **Trap #3:** after many
   link bounces the GID table can get holes (IPv4 v2 at index 4, index 3 empty). `nmcli con down/up` the
   profile repacks it.
6. **Controller prerequisites** (we use rank 0 as controller): the controller must be able to SSH to *all
   three* ranks non-interactively **including itself** (add its own public key to its `authorized_keys`),
   and all three host keys must be in `known_hosts`. Preflight otherwise fails with
   `Host key verification failed` / `Permission denied`.
7. **`.env`:** start from `env/env.example` here (three ranks, two fabric legs each, `tailscale0` as socket
   interface, GID 3). **The recipe insists on `JSPARK_API_PORT=8000` and master port 29533.**
8. **Apply the fork** on the controller, then sync `recipe/` to the other ranks:
   ```bash
   cd ~/recipe-jspark3/recipe && python3 /path/to/patches/jspark3-fork-patch.py
   for h in worker-1 worker-2; do rsync -a --delete --exclude .env ~/recipe-jspark3/recipe/ $h:~/recipe-jspark3/recipe/; done
   ```
   The patch removes `--language-model-only`, adds `--skip-mm-profiling --limit-mm-per-prompt '{"image":400,"video":1}'`,
   sets utilisation 0.78 and rewrites the `SHA256SUMS` line for `fleetctl.py` (the preflight runs
   `sha256sum -c`). Backups land in `~/recipe-jspark3/fork-backups/` — **not** inside `recipe/`, see trap #4.
9. **Preflight and start** (jspark3 `docs/INSTALL.md` §7):
   ```bash
   ./scripts/clean-room-setup.sh --env-file .env --output preflight.json
   ./scripts/start.sh --env-file .env --preflight preflight.json --preflight-sha256 "$(sha256sum preflight.json | cut -d' ' -f1)" --confirm START-JSPARK3
   ```
   Starts rank 2, 1, 0. First boot ~18 min (cold page cache), ~13 min after that. NCCL init over the
   triangle took 2.65 s. Ignore a `usage_lib`/`cpuinfo` JSON traceback in rank 0's log — it is vLLM's
   telemetry thread and harmless.
10. **Restart traps (#4–#7)** — every one of these refused a restart for us:
    - extra files inside `recipe/` (e.g. `.orig` backups) → `recipe inventory mismatch`;
    - the previous `jspark3-release-manifest.json` → `release manifest already exists`;
    - the previous `~/jspark3-work/rank*/evidence/` → `FileExistsError: image-receipt.json`;
    - a container a refused start left behind → `deterministic release name already exists`
      (`docker rm -f jspark3-rank*` on every node).
    Working order: `stop.sh … --remove` → move the manifest and `~/jspark3-work` aside on all ranks →
    remove stray containers → `clean-room-setup.sh` → `start.sh`.

## Step 11 (optional, +30–40 % prefill): MiaAI-Lab's E3 grouped fat-expert MoE kernels

The jspark3-pinned image (28 Aug) predates Mia's E2/E3 fat-expert kernels. Both images run the same vLLM
build, torch 2.13.0+cu130 and exllamav3 0.0.43, so E3 can be layered on without changing the image digest:

1. **Build the additive kernel module inside the pinned image** (53 s on a GB10, no GPU needed for the build,
   but `--gpus all` is the easy way to get the CUDA runtime). Needs a checkout of
   `MiaAI-Lab/GLM-5.3-Flash-EXL3-2x-DGX-Sparks` (AGPL-3.0; nothing of it is redistributed here):
   ```bash
   M=~/GLM-5.3-Flash-EXL3-2x-DGX-Sparks/overlay; mkdir -p ~/e3build/out
   cp $M/exl3_fat_moe.cu $M/exl3_fat_moe.cuh $M/build_exl3_fat_moe_ext.py ~/e3build/
   docker run --rm --gpus all --memory 6g -e MAX_JOBS=1 -v ~/e3build:/build --entrypoint python3 \
     ghcr.io/miaai-lab/glm-5.3-flash-2x-dgx-sparks@sha256:9bb1557a4234fce63d59599e44d10747eabd742beb337eebf9e7070be8a0fd58 \
     /build/build_exl3_fat_moe_ext.py --src /build --out /build/out
   mkdir -p ~/recipe-jspark3/e3 && cp ~/e3build/out/exl3_fat_moe_ext.so ~/recipe-jspark3/e3/   # then copy to every rank
   ```
2. **Merge Mia's current `overlay/exl3.py`** (carries the E2/E3 tiers) **with FlyCockpit's two TP3/EP load fixes:**
   `python3 patches/e3-merge-exl3.py $M/exl3.py` → `/tmp/exl3_merged.py`. Copy it to every rank.
3. **Apply `patches/jspark3-e3-patch.py /tmp/exl3_merged.py` on every rank** (idempotent). It replaces the
   FlyCockpit overlay file, then chases the sha through every layer jspark3 pins it in — and there are many:
   - `scripts/_contracts.py` and `config/patch-contract.json` (exl3.py source/after sha),
   - `scripts/fleetctl.py`: recomputed `transform_target_set_sha256`, the E3 env
     (`EXL3_FAT_GROUPED=1 EXL3_TEMP_ROWS_FUSED=32 MAX_NUM_BATCHED_TOKENS=8192`), a read-only bind mount of the
     `.so` into the container's `dist-packages`, **and** the same mount in `expected_mounts` (otherwise
     `rankN mount contract drift`),
   - `modules/b5_prefix_verify.py`: the Cadence module's own hash gate over image files (otherwise the container
     dies with `B5_PREFIX_VERIFY_REFUSE hash gate failed: exl3.py`, exit 9, right after "Using max model len"),
     which in turn is pinned in `fleetctl.py B45_MODULES` and `config/cadence-contract.json`,
   - the `SHA256SUMS` rows for all of the above.
4. **Two more traps:** run `stop.sh` *before* changing `SHA256SUMS` (afterwards it refuses with
   `manifest does not bind this environment/image`), and delete `recipe/scripts/__pycache__` if anything imported
   the recipe modules (`generated/private recipe directory`). Then step 9 again.

You know it worked when rank 0 logs `exl3 e2 diag … configured_tier=grouped effective_tier=grouped tier_reason=grouped_ok
sym_fat_moe=1`. KV pool 1,786,610 → 1,778,242 tokens (the E3 scratch), memory headroom unchanged. Cold prefill
(unique prompts, `scripts/prefill-bench.py`): see `results/bench-2026-09-14.md` — roughly 1,200 → 1,600–1,750 tok/s.

## Using it

- OpenAI-compatible API on rank 0, port 8000, model id **`glm-5.3-flash`**, 1M context, images accepted
  (`image_url` with base64 or URL), thinking off by default; pass `chat_template_kwargs: {"enable_thinking": true, "reasoning_effort": "low|high|max"}`.
- We keep our tools pointed at port 8888 with a plain nginx passthrough → 8000 (`examples/nginx-8888-passthrough.conf`)
  and a per-key proxy for friends with `limit_conn 1` per key, so nobody's parallel agents queue in front of yours.
- Harness snippets that work: see `examples/harness-configs.md` (DeepSeek Harness/dsh, ZCode, Hermes, omp).

## What's next (not done here)

- Mia's small NCCL buffers (`NCCL_BUFFSIZE=1048576`, `NCCL_LL128_BUFFSIZE=262144`, `NCCL_PROTO=^LL128`)
  freed 4.7 GB of pinned memory per node on two nodes; jspark3's env parser forbids `NCCL_PROTO`, so this
  needs a small launcher change.
- Compare Mia's adaptive-K verification with jspark3's own "cadence" speculative-width controller.

## Credits

- **jakejharris/jspark3** — the launcher, preflight, TP3/EP3 runtime views, W8A16 dense overlay (Apache-2.0; `patches/fleetctl.py.diff` is a modification of `recipe/scripts/fleetctl.py`, see NOTICE).
- **FlyCockpit** — the original TP3 + expert-parallel technique on Mia's image (MIT).
- **MiaAI-Lab** — the engine image, the E3 kernels and most of what makes GLM-5.3-Flash run well on GB10 at all (AGPL-3.0; image pulled from GHCR, not redistributed).
- **NNNtrance** — the hotplug fix and the most thorough three-Spark hardware write-up available.
- **brandonmusic / Mia-AiLab** (EXL3 checkpoint), **turboderp** (ExLlamaV3), **incoai** (DFlash2 drafter), **Z.ai** (GLM-5.3-Flash, MIT).

Everything in this repository that is ours is MIT. Measurements are from our own three boxes and will
differ on yours.
