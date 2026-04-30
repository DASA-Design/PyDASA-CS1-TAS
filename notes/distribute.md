# Distribute: client / TAS / atomics across machines

> **STATUS: DEFERRED (2026-04-30).** Not in active use. The single-laptop
> path with specs-layer μ-binpacking covers the current case-study scope.
> Apply this plan when work splits across machines (UDS transport, Linux
> hosts, multi-node sweeps). See memory entry
> `project_uds_transport_deferred.md` for the trigger conditions.

Plan for letting the experiment method run distributed -- client on one
machine, TAS composite on another, atomics on a third (or any merging of
those three roles into fewer machines). Today every node is `127.0.0.1`
on a single laptop; this plan adds **per-role host endpoints** to the
config + a **deployment-mode parameter** on `run()` so the same code path
serves both `local` and `remote` deployments without behaviour drift.

Pairs with:

- `notes/scale.md` -- the vernier service plan; vernier runs `local`-only
  and is unaffected.
- `notes/scale-2.md` -- the Route-B measured sweep; same `local` model,
  unaffected.
- `notes/calibration.md` -- P3 / P4 originally captured "remote-ready
  packaging" + "LAN deployment" as deferred work. **This plan supersedes
  P3 / P4** of `notes/calibration.md` for the experiment method; the
  calibration probe stays single-host.
- `CLAUDE.md` "Async load drivers" section -- the deterministic-rate
  recipe holds across hosts; no change.

## 1. The problem this solves

Today the experiment method assumes one machine:

- `data/config/method/experiment.json::host = "127.0.0.1"` is a single
  string; every service in `service_registry` resolves through it.
- `SvcRegistry.from_config(method_cfg)` builds one registry with one
  shared host + base port; `resolve_base_url(name)` returns
  `http://127.0.0.1:<base+offset>` for every service.
- `ExperimentLauncher` spawns every service (TAS_{1..6} composite, every
  atomic) in-process via uvicorn threads. There is no way to say "TAS
  composite is on machine B, atomics live on machine C, my client on
  machine A".

The case study only delivers credible numbers when the topology can run
distributed -- one machine doing client + TAS + atomics is artificially
quiet because intra-process calls bypass real TCP. **Calibration's
loopback floor (~3 ms) already proves that the single-host story
under-estimates the real per-hop cost**, but until the experiment can
actually send requests across a LAN we cannot quantify the gap.

## 2. Scope and non-scope

**In scope** (single PR, mirrors scale-2.md's discipline):

- Per-role host overrides in `data/config/method/experiment.json`.
  Additive -- the existing top-level `host` stays as the default; the
  new `hosts` block lets a deployment override individual roles
  without rewriting the registry table.
- New `deployment` enum on `experiment.json`, **3 values**: `local`
  (today's fast-path 127.0.0.1 behaviour) / `loopback_aliased`
  (single-host honest bench using `127.0.0.10/20/30` aliases per
  bucket, see §11) / `remote` (per-bucket hosts honoured, services NOT
  spawned in-process).
- New `dpl: str = "local"` parameter on
  `src.methods.experiment.run(adp, prf, scn, wrt, dpl, ...)`. Defaults
  to the JSON's value, falls back to `"local"`. CLI grows
  `--deployment {local,loopback_aliased,remote}`.
- `SvcRegistry.from_config` learns to resolve per-service host from
  `hosts.<role>` (or `hosts.<service_name>` when finer-grained), with
  fallback to the top-level `host`.
- `ExperimentLauncher` learns a `deployment` knob: `local` keeps
  today's full-mesh in-process spawn; `remote` only validates that
  each non-local service is reachable (`/healthz`) and skips the
  in-process startup of those services.
- New launcher script(s) `src/scripts/launch_tas.py` and
  `launch_atomics.py` for standing up the TAS composite or the atomic
  fleet on a non-client machine. Read the same `experiment.json`; bind
  to the host they were configured for.
- Config-driven host mapping for the **4 canonical layouts**:

  | Layout | Mode | Client | Composite TAS | Atomics | `launcher_role` per machine |
  |---|---|---|---|---|---|
  | `local` (today) | `local` | A | A | A | A: `all` |
  | single-host honest | `loopback_aliased` | A:`127.0.0.10` | A:`127.0.0.20` | A:`127.0.0.30` | A: `all` |
  | 2-way | `remote` | A | B | B | A: `client`, B: `composite-atomic` |
  | 3-way | `remote` | A | B | C | A: `client`, B: `composite`, C: `atomic` |

  `loopback_aliased` is the same machine A in three places; aliases
  force every hop through the kernel routing layer (see §11). 2-way
  and 3-way are real LAN deployments.

**Out of scope** (ruled out by single-PR discipline):

- Encryption / TLS / auth on the inter-host hops. LAN-only assumption,
  documented in `notes/distribute.md` (this file).
- Per-atomic host selection (separate machines for `MAS_{1}` vs
  `AS_{1}`). The plan covers role-level mapping; per-service mapping is
  an additive `hosts.<service_name>` lookup that the `from_config`
  helper already supports trivially (specified below) but no
  configuration ships with it populated.
- Cross-host clock-skew mitigation. The `notes/calibration.md` rule
  already pins this: every timestamp computation stays within one
  host's `perf_counter_ns` clock; only `request_id` crosses hosts.
- Calibration sweep across hosts. Calibration runs on each host
  individually; the per-host envelope continues to live under
  `data/results/experiment/calibration/<hostname>_<ts>.json`.
- A new `dpl` axis on the artifact path (e.g. `data/results/experiment/local/...`
  vs `.../remote/...`). Already done as part of `notes/calibration.md`
  P3.1 -- the directories `data/results/experiment/local/` and
  `data/results/experiment/remote/` already exist with `.gitkeep`
  markers; this plan just starts writing into them.

## 3. Config schema additions

**File**: `data/config/method/experiment.json`

**Add three additive keys** (no rename, no deletion of existing keys):

```json
{
    "base_port": 8001,
    "host": "127.0.0.1",
    "deployment": "local",
    "hosts": {
        "client":    "127.0.0.10",
        "composite": "127.0.0.20",
        "atomic":    "127.0.0.30"
    },
    "network": {
        "transport": "loopback_aliases",
        "notes": "Single-host honest bench by default; LAN deployment overrides hosts to real IPs and sets transport='wired_ethernet'."
    },
    "healthz_timeout_s": 10,
    ...
    "service_registry": {
        ...
    }
}
```

The `hosts` defaults are the loopback aliases used by
`loopback_aliased` mode; in `local` mode the block is ignored and
every service uses top-level `host` (= `127.0.0.1`); in `remote` mode
the operator overrides each bucket with a real LAN IP.

The `network` block is **descriptive metadata**, not behaviour. It
ships in the result envelope's `host_profile` so every persisted
`<host>_<ts>.json` records the deployment medium that produced the
numbers. The smoke harness in G6 (§7) reads the second-machine address
from the same `hosts.<bucket>` keys; no separate "smoke target" config
is needed.

**Resolution order** per `deployment` mode:

| Mode | Bind address | Service host resolution |
|---|---|---|
| `local` | `127.0.0.1` | every service uses top-level `host` (`127.0.0.1`); `hosts` block ignored. Today's behaviour. |
| `loopback_aliased` | `0.0.0.0` | per-service-name `hosts[N]` if set, else per-bucket `hosts[R]`, else `host`. Defaults are loopback aliases (`127.0.0.10/20/30`). |
| `remote` | `0.0.0.0` | identical resolution to `loopback_aliased`; only the IPs in the JSON differ (LAN addresses instead of loopback aliases). |

`loopback_aliased` and `remote` share the entire code path; the only
difference is what the operator wrote in the `hosts` block. This
keeps the implementation tiny: one enum check distinguishes `local`
(fast-path 127.0.0.1, `hosts` ignored) from the other two (per-bucket
resolution).

**Role-to-bucket mapping**:

| Bucket key | service_registry roles included |
|---|---|
| `client` | `composite_client` (drives the ramp; collocated with the simulator) |
| `composite` | `composite_medical`, `composite_alarm`, `composite_drug` (TAS_{2..6} business logic) |
| `atomic` | `atomic` (every MAS / AS / DS) |

**Concrete deployment examples** (each replaces the `hosts` block):

```json
// local (default; today's behaviour, fastest dev loop)
"deployment": "local",
"hosts": { "client": null, "composite": null, "atomic": null }

// loopback_aliased: single-host honest bench (see §11)
"deployment": "loopback_aliased",
"hosts": {
    "client":    "127.0.0.10",
    "composite": "127.0.0.20",
    "atomic":    "127.0.0.30"
}

// 2-way remote: client on A, everything else on B
"deployment": "remote",
"hosts": {
    "client":    "192.168.1.10",
    "composite": "192.168.1.20",
    "atomic":    "192.168.1.20"
}

// 3-way remote: client on A, composite on B, atomics on C
"deployment": "remote",
"hosts": {
    "client":    "192.168.1.10",
    "composite": "192.168.1.20",
    "atomic":    "192.168.1.30"
}
```

**Why role-bucketed, not per-service**: covers the realistic deployment
shapes you sketched ("client on A, TAS on B, atomics on C") in one
2-line edit. Per-service overrides remain available via `hosts.<svc>`
for the rare case where one atomic needs its own machine, but the
default config never populates that level.

## 4. Code changes

### 4.1 `src/experiment/registry.py`

Update `SvcRegistry.from_config` to accept the new `hosts` block and
resolve per-service host. Adds a new `host_for(name)` accessor that the
URL builders use instead of the bare `self.host`:

```python
@dataclass(frozen=True)
class SvcRegistry:
    host: str
    base_port: int
    table: Dict[str, RegistryEntry]
    host_overrides: Dict[str, str] = field(default_factory=dict)  # NEW

    @classmethod
    def from_config(cls, method_cfg, *, base_port_override=0):
        _host = method_cfg.get("host", "127.0.0.1")
        _hosts_block = method_cfg.get("hosts", {}) or {}
        _deployment = method_cfg.get("deployment", "local")
        # build per-service overrides; in 'local' mode they collapse to {host}
        _overrides = {}
        for _name, _spec in method_cfg["service_registry"].items():
            _role = _spec["role"]
            if _deployment == "local":
                _overrides[_name] = _host
                continue
            # per-service > per-role-bucket > top-level host
            if _hosts_block.get(_name):
                _overrides[_name] = _hosts_block[_name]
            elif _role.startswith("composite_client"):
                _overrides[_name] = _hosts_block.get("client") or _host
            elif _role.startswith("composite_"):
                _overrides[_name] = _hosts_block.get("composite") or _host
            elif _role == "atomic":
                _overrides[_name] = _hosts_block.get("atomic") or _host
            else:
                _overrides[_name] = _host
        # rest of from_config unchanged ...

    def host_for(self, name: str) -> str:
        return self.host_overrides.get(name, self.host)

    def resolve_base_url(self, name: str) -> str:
        _e = self.table[name]
        return f"http://{self.host_for(name)}:{_e.port}"
```

`build_invoke_url` and `build_healthz_url` already call
`resolve_base_url`, so they pick up the per-service host transparently.

### 4.2 `src/experiment/launcher.py`

`ExperimentLauncher.__init__` learns:

- `deployment: str = "local"` keyword (defaults to JSON value).
- `launcher_role: str = "all"` keyword (which bucket THIS process is
  responsible for spawning).
- An internal `_local_services: Set[str]` set of service names this
  launcher is responsible for spawning, computed from
  `(deployment, launcher_role)` and the registry.

Resolution rule (decided 2026-04-25 with the user): **default is "all
local"**. To go distributed, the operator picks **one** of the three
buckets to host THIS process, and the other two read their IPs from
JSON. Other two can resolve to one IP each (3-machine fan-out) or to
the same IP (2-machine fan-out) -- the registry doesn't care. The same
JSON ships unchanged to every host; each host distinguishes itself only
by the `--launcher-role` value passed at startup.

| Mode | `launcher_role` | Local services on this host |
|---|---|---|
| `local` (default) | `"all"` (forced, ignored if explicit) | every service in `service_registry` (today's behaviour) |
| `loopback_aliased` | `"all"` | every service, but each bucket binds to its `127.0.0.X` alias instead of `127.0.0.1` (single host, three IPs in flight) |
| `remote` | `"client"` | `composite_client` services only (TAS_{1}, TAS_{5}, TAS_{6}); the simulator's entry point |
| `remote` | `"composite"` | `composite_medical`, `composite_alarm`, `composite_drug` (TAS_{2..4}) |
| `remote` | `"atomic"` | every `atomic` service (MAS / AS / DS) |
| `remote` | `"composite-atomic"` | `composite_*` (TAS_{2..6}) **plus** every atomic service. The client lives on the other machine; this machine carries everything else. The 2-machine A+B layout. |
| `remote` | `"all"` | every service (single-machine remote run; useful for staging the JSON before splitting) |

In `remote` mode the launcher reads the IPs of the two non-local
buckets from `hosts.<bucket>`; the registry resolves URLs to those
remote hosts. Health barrier polls every entry's `/healthz` regardless
of locality, so a misconfigured remote IP fails fast at startup
instead of mid-run.

`__aenter__` and `__aexit__` only spawn / tear down `_local_services`.
Health barrier (`await every /healthz`) still polls **every** service,
so the launcher refuses to start until remote nodes are reachable too.

### 4.3 `src/methods/experiment.py`

Two new run-time parameters threaded through `run()`:

```python
def run(adp=None, prf=None, scn=None, wrt=True,
        method_cfg=None, skip_calibration=False, verbose=True,
        dpl: Optional[str] = None,                    # NEW
        launcher_role: str = "all") -> Dict[str, Any]:
    ...
    # resolve deployment from CLI > arg > JSON > "local"
    _deployment = dpl or _mcfg.get("deployment", "local")
    _mcfg = dict(_mcfg)
    _mcfg["deployment"] = _deployment
    ...
```

`_run_async` passes both into `ExperimentLauncher(..., deployment=_dpl,
launcher_role=launcher_role)`.

Output paths split by mode (matches `notes/calibration.md` P3):

- `local`: `data/results/experiment/local/<scenario>/<profile>/...`
  (existing `data/results/experiment/local/` directory).
- `loopback_aliased`: `data/results/experiment/loopback_aliased/<scenario>/<profile>/...`
  (NEW directory; created at G4 alongside the writer change).
- `remote`: `data/results/experiment/remote/<scenario>/<profile>/...`
  (existing `data/results/experiment/remote/` directory).

Every persisted run's envelope carries `network.transport` so a stale
grep tells you which medium produced the numbers regardless of path.

`_build_output_path` learns a `deployment` axis; today's bare paths get
moved under `local/` (already done in P3.1, see `notes/calibration.md`
2026-04-23 entry).

### 4.4 New launcher script (one, not two)

One thin launcher script under `src/scripts/`:

```python
# src/scripts/launch_services.py
"""Spawn the subset of services this machine is responsible for.

Reads data/config/method/experiment.json for ports + hosts, then
spawns whichever services match --launcher-role. Auto-binds 0.0.0.0
when --deployment=remote (overridable via --bind).

Examples (same JSON file shipped to every machine):

    # 2-machine layout, machine B (services side):
    python -m src.scripts.launch_services --launcher-role=composite-atomic

    # 3-machine layout:
    python -m src.scripts.launch_services --launcher-role=composite       # machine B
    python -m src.scripts.launch_services --launcher-role=atomic          # machine C
"""
```

Reuses `ExperimentLauncher(launcher_role=..., deployment="remote")` with
the appropriate role; keeps the process alive (`await asyncio.Future()`)
until SIGINT. **One script** covers every remote-machine case
(`composite`, `atomic`, `composite-atomic`); collapsing the
previously-planned `launch_tas.py` + `launch_atomics.py` into one
removes a needless script split now that `launcher_role` is the single
selector.

**Bind address auto-flip** (decided 2026-04-25 with the user). Uvicorn
takes a different kernel path depending on the bind address:

- Bind `127.0.0.1`: kernel loopback fast path; IP stack is
  short-circuited (no NIC, no ARP, no routing). Loopback latency floor
  is ~3 ms (per current calibration).
- Bind `0.0.0.0`: full IP-stack hop, even for local clients. Loopback
  latency typically rises by 50-200 us because the path traverses the
  loopback interface but with the routing layer engaged.

The launcher therefore picks the bind address from `deployment`:

| `deployment` | Bind address (auto) | Why |
|---|---|---|
| `local` | `127.0.0.1` | Today's behaviour; keeps the dev-loop floor on the kernel fast path. |
| `loopback_aliased` | `0.0.0.0` | Each service must accept connections from a different `127.0.0.X` alias on the same machine; the `0.0.0.0` bind catches every alias on the loopback interface. |
| `remote` | `0.0.0.0` | Service must accept connections from a different host on the LAN; same path used regardless of caller location. |

The `--bind` CLI flag remains available on the launcher scripts as an
explicit override (e.g. `--bind 127.0.0.1` while staging a `remote`
config on one machine for smoke testing). Unset, the deployment-driven
default applies.

### 4.5 CLI surface

`src/methods/experiment.py::main` adds:

```
--deployment {local,loopback_aliased,remote}     deployment mode override
--launcher-role {all,client,composite,atomic,composite-atomic}
                                only relevant when --deployment=remote;
                                picks WHICH bucket runs locally on
                                this host. The other buckets read their
                                IPs from hosts.<bucket> in the JSON.
                                Defaults to "all" (today's behaviour).
                                Use "composite-atomic" for the 2-machine
                                layout (client on A, services on B).
--bind {127.0.0.1,0.0.0.0,...}   explicit override for the uvicorn bind
                                address. Unset, the default auto-flips:
                                local -> 127.0.0.1, remote -> 0.0.0.0.
```

The launcher scripts (`launch_tas.py`, `launch_atomics.py`) accept
the same `--bind` flag for parity.

## 5. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Wire-schema drift: adding `deployment` and `hosts` to the JSON breaks loaders that did not expect them | Low | Medium | Both keys are additive with explicit defaults; `dict.get` calls cover missing keys. Existing tests stay green because the JSON's `deployment` defaults to `"local"`. |
| Health barrier hangs because remote machine is not up yet | High | Medium | Existing `healthz_timeout_s` (10s default) is too short for a manual remote start. Bump to 60s when `deployment=remote` and document the manual-start sequence in `notes/quickstart.md`. |
| Mixed-mode misconfiguration (`deployment=local` with `hosts.composite=192.168.x.y`) | Medium | Low | `local` mode IGNORES the `hosts` block by design (see §3). Add a launcher-startup log line `"deployment=local, ignoring hosts overrides"` so the operator notices. |
| Cross-host clock skew distorting `client_effective_rate` vs entry-service `lambda` | Medium | High | Per `notes/calibration.md` rule: every timing math stays within one host. The client measures `effective_rate` against its own clock; entry-service `lambda` is measured by the composite machine's clock. They should agree by Little's law steady state, not by clock arithmetic. Test invariant: `\|client_effective_rate - entry_lambda\|` stays under 1 % across deployment modes. |
| Firewall blocks inter-host traffic | High (Windows Defender by default) | High | Document the port-allowlist step (composite ports `8001..8006`, atomic ports `8007..8016`) in `notes/quickstart.md` per P4.3 of `notes/calibration.md`. Add a pre-run reachability check in the launcher: ping each remote host's `/healthz`, fail fast with a "firewall? is the composite up?" message if unreachable. |
| `0.0.0.0` bind exposes services to the LAN | Low (LAN-only deployment) | Medium | Documented in CLAUDE.md and the launcher script docstrings: scripts are NOT for production use; LAN-only assumed. The launcher scripts are dev tools, not services. |
| `0.0.0.0` bind shifts the loopback floor in `remote` mode | High | Low (it's WHAT we want) | Auto-flip is intentional: `local` keeps `127.0.0.1` for the kernel loopback fast path; `remote` flips to `0.0.0.0` so even local clients pay the full IP-stack hop, matching what cross-host clients pay. Both floors get re-baselined with the calibration probe in `remote` mode -- the gap between the two floors is itself a documented case-study finding. |
| Different Python / wheel versions across machines drift the prototype | Medium | High | `requirements.txt` is pinned; the deployment guide instructs same-commit + same-wheel install on every machine. CI does not enforce this; flag in the post-run envelope (`host_profile.python` + commit SHA) so a mismatch is auditable. |
| Distributed mode adds setup time per audit run; tempting to only run `local` | High | Medium -- under-reports real-world latency | Document in `CLAUDE.md` that the canonical case-study numbers come from `remote` mode; `local` mode is the dev loop, not the deliverable. |

## 6. Effort + sequencing

| Step | Deliverable | Effort | Dependencies |
|---|---|---|---|
| S1 | JSON additions: 3-mode `deployment` enum + `hosts` block populated with `127.0.0.10/20/30` aliases + `network` metadata block | 0.05 d | -- |
| S2 | `SvcRegistry.from_config` resolves per-service host (one enum check distinguishes `local` from `loopback_aliased` / `remote`) | 0.25 d | S1 |
| S3 | `ExperimentLauncher` learns `deployment` + `launcher_role`; only spawns local subset; bind auto-flip (`local` -> `127.0.0.1`, others -> `0.0.0.0`) | 0.5 d | S2 |
| S4 | `experiment.py::run` grows `dpl` + `launcher_role` parameters; output path splits by deployment axis (`local/`, `loopback_aliased/`, `remote/`) | 0.25 d | S3 |
| S5 | `src/scripts/launch_services.py` (~80 lines); reuses `ExperimentLauncher` with `launcher_role` from CLI; covers every remote-machine case in one script | 0.2 d | S4 |
| S6 | Tests: registry per-host resolution covering all 3 modes; launcher subset selection; `run()` with `dpl=remote` against an in-process fake-remote (`httpx.MockTransport`) | 0.5 d | S2-S4 |
| S6b | Single-host honest bench: run calibration + experiment in `loopback_aliased` mode on `DESKTOP-INKGBK6`; document the floor delta vs `local` | 0.5 d | S5 |
| S7 | LAN smoke: actually run the 2-way layout on `DESKTOP-INKGBK6` -> a second host; record loopback p99 and one-trial run numbers | 0.5 d | S6b (genuine LAN gear) |
| S8 | Update `notes/quickstart.md` with the 4 deployment recipes (local / loopback_aliased / 2-way / 3-way); CLAUDE.md "Distributed deployment" paragraph; `notes/calibration.md` P3-P4 marked SUPERSEDED | 0.1 d | S7 |
| **Total** | -- | **~2.85 d** (with LAN smoke) or ~2.35 d without S7 (single-host honest numbers still ship) | -- |

Recommended order: **S1 -> S2 -> S6 (registry tests) -> S3 -> S6 (launcher tests) -> S4 -> S6 (run tests) -> S5 -> S7 -> S8**.

## 7. Audit gates

Mirrors scale.md / scale-2.md gating discipline:

| Gate | Artifact you audit | Pass criterion | Status |
|---|---|---|---|
| **G1** | JSON additions in `data/config/method/experiment.json`: 3-mode `deployment` enum, `hosts` block defaulted to `127.0.0.10/20/30`, `network` metadata block; existing keys untouched | `python -c "from src.io import load_method_cfg; print(load_method_cfg('experiment'))"` round-trips; default `deployment=local` matches today's behaviour. | PENDING |
| **G2** | `SvcRegistry` diff: `host_overrides` field, `host_for()` accessor, updated `from_config` covering all 3 modes | `local`: every service -> `127.0.0.1`. `loopback_aliased`: client -> `127.0.0.10`, composite_* -> `127.0.0.20`, atomic -> `127.0.0.30`. `remote`: same resolution as `loopback_aliased` but with operator-supplied LAN IPs. New unit tests in `tests/experiment/test_registry.py` parametrised over all 3 modes. | PENDING |
| **G3** | `ExperimentLauncher` diff: `deployment` + `launcher_role`; bind auto-flip (`local` -> `127.0.0.1`, others -> `0.0.0.0`); `_local_services` set determines which services to spawn | `launcher_role="client"` spawns only composite_client; `launcher_role="atomic"` spawns only atomic services; `launcher_role="all"` (default) spawns everything; `loopback_aliased` mode binds `0.0.0.0` so each `127.0.0.X` alias is reachable; health barrier still polls every service in the registry. | PENDING |
| **G4** | `experiment.py::run` diff: new params; output path split by deployment axis | `run(dpl="local")` writes to `local/<scenario>/<profile>/`; `run(dpl="loopback_aliased")` writes to `loopback_aliased/<scenario>/<profile>/`; `run(dpl="remote")` writes to `remote/<scenario>/<profile>/`; `_paths` keys carry the new axis. New `loopback_aliased/` directory created with `.gitkeep`. | PENDING |
| **G5** | New `src/scripts/launch_services.py`; runs cleanly with `--launcher-role={composite,atomic,composite-atomic,all}` against today's config | `python -m src.scripts.launch_services --launcher-role=all --deployment=local` brings up TAS_{1..6} + atomics on 127.0.0.1; `Ctrl-C` shuts down cleanly. `--launcher-role=composite-atomic` brings up only TAS_{2..6} + atomics, skipping TAS_{1} / TAS_{5} / TAS_{6}. | PENDING |
| **G6** | Single-host honest bench: `python -m src.methods.calibration --deployment=loopback_aliased` then full experiment under `loopback_aliased`; pasted numbers vs the existing `local` envelope | Loopback floor in `loopback_aliased` is **higher** than `local` by 50-500 us (or identical, if the kernel optimises cross-alias loopback -- a documented finding either way). `W_net` for the 4-hop journey shifts up proportionally. Both envelopes persist with their own `network.transport` tag. | PENDING |
| **G7** | LAN smoke: 2-way deployment on real hardware (one machine = `composite_client`, second machine = composite + atomics); pasted output | At least one full ramp completes; `client_effective_rate` reported; agreement with the entry-service `lambda` within 1 %. Saturation rate documented. | PENDING (gated on second-machine availability) |
| **G8** | Documentation sync: `notes/quickstart.md`, `CLAUDE.md`, `notes/calibration.md`, `notes/devlog.md` | All four files updated; P3 / P4 of `notes/calibration.md` marked SUPERSEDED with a pointer to this file; CLAUDE.md gains a "Distributed deployment" subsection covering the 3-mode mental model from §11.4. | PENDING |

**Audit batches** (rollback points):

- **Batch 1: G1 + G2 + G3 + G4** -- pure code + JSON changes in isolation; revert is `git restore` of 4 files.
- **Batch 2: G5** -- launcher script (one new file); revert is one `git rm`.
- **Batch 3: G6** -- single-host honest bench; passive observation, no rollback. **Ships honest single-host numbers regardless of LAN-hardware availability.**
- **Batch 4: G7** -- LAN smoke; passive observation, no rollback. Gated on second-machine availability.
- **Batch 5: G8** -- docs sync.

## 8. Summary table

| Dimension | Value |
|---|---|
| **Estimate (calendar)** | ~2.85 working days from green start to G8 close (with LAN smoke); ~2.35 d without G7 (single-host honest numbers ship from G6 regardless) |
| **Estimate (effort, no waiting)** | ~17-19 hours of focused work |
| **Files added (1)** | `src/scripts/launch_services.py` (one script handles every remote-machine role via `--launcher-role`) |
| **Files edited (4)** | `data/config/method/experiment.json` (additive: 3-mode `deployment` enum + `hosts` block defaulted to `127.0.0.10/20/30` + `network` metadata); `src/experiment/registry.py` (new field + accessor); `src/experiment/launcher.py` (new params + subset spawning + bind auto-flip); `src/methods/experiment.py` (new params + path split incl. `loopback_aliased/`) |
| **Files NOT touched** | `src/experiment/services/{base,instruments,atomic,composite,vernier}.py`; `src/experiment/payload.py`; `src/experiment/client.py`; calibration runner; vernier; LOG_COLUMNS; profile JSONs; PACS variable schemas; all wire schemas other than the additive `experiment.json` keys |
| **Lines of code (rough)** | ~50 in registry + ~80 in launcher + ~40 in experiment.py + ~80 in one launcher script + ~150 in tests = ~400 net |
| **Default cost** | 0 -- `deployment=local` keeps today's behaviour; remote mode is opt-in via JSON or CLI |
| **Top risk** | Firewall + LAN configuration on a real second host (G7 only); mitigated by allowlist documentation + reachability pre-flight check. G6 ships single-host honest numbers regardless of LAN status. |
| **Top blocker** | None foreseen for code; physical access to a second LAN-attached machine for G6 is the main external dependency |
| **Reversibility** | High -- two new files + 4 additive edits; revert is mechanical |
| **What this proves** | The DASA case study numbers can be regenerated under realistic distributed conditions, not just on a single laptop. The `local` vs `remote` delta becomes a documented, comparable artifact. |

## 9. Plan-level decisions (closed 2026-04-25)

Resolved with the user; baked into §3-§5 above.

1. **Default ergonomics = per-role buckets** (`hosts.client/composite/atomic`). Per-service overrides remain available via `hosts.<service_name>` but no shipped config populates them.
2. **`launcher_role` semantics**: default = `"all"` (local mode = today's behaviour). In `remote` mode the operator picks **one** of the three buckets to host THIS process, and the other two read their IPs from `hosts.<bucket>`. The non-local buckets can resolve to one IP each (3-machine fan-out) or to the same IP (2-machine fan-out); the registry is agnostic. The same `experiment.json` ships unchanged to every host; each machine distinguishes itself only by `--launcher-role` at startup.
3. **`0.0.0.0` bind auto-flips** with `deployment`: `local` -> `127.0.0.1` (kernel loopback fast path; preserves today's ~3 ms floor), `remote` -> `0.0.0.0` (full IP-stack hop on every call, including local). `--bind` CLI flag remains as an explicit override; unset, deployment-driven default applies.
4. **G6 hardware = wired Ethernet, second machine address comes from the same `hosts.<bucket>` JSON keys**. The new `network` block in `experiment.json` records the medium descriptively and threads through to `host_profile` in the result envelope. No separate smoke-target config.
5. **Path split** (open): `data/results/experiment/local/` and `remote/` directories already exist with `.gitkeep` markers (per `notes/calibration.md` 2026-04-23 entry). This plan writes into them. **Open**: are there still legacy outputs under the bare `data/results/experiment/<scenario>/...` path that need to be moved under `local/` first? Inspect and decide at G4 execution time.

The plan above incorporates these answers; implementation proceeds gate-by-gate.

## 10. Decision (closed 2026-04-25): fold loopback_aliases plan in here

The earlier `notes/loopback_aliases.md` plan has been folded into this
file as §11 below. Both plans share identical machinery (per-bucket
host resolution, bind auto-flip, launcher subset selection); merging
them removes a duplicate audit trail without losing capability. The
3-mode `deployment` enum (`local` / `loopback_aliased` / `remote`)
ships from G1 onward.

## 11. Single-host honest benching: loopback aliases

`loopback_aliased` mode binds each role bucket to a distinct loopback
alias (client `127.0.0.10`, composite `127.0.0.20`, atomic
`127.0.0.30`) so cross-bucket traffic engages the kernel routing
layer. The `.10 / .20 / .30` spacing leaves `127.0.0.{1-9}` free for
ad-hoc dev use, `127.0.0.{11-19}` for future client overrides, etc.

### 11.1 The problem this solves

Today's `local` mode collapses every TAS hop into a Python function
call -- composite siblings dispatch via the shared `_handlers` dict,
bypassing HTTP entirely (~50 us per hop). A 4-hop journey costs
~0.2 ms. On a real LAN the same journey costs 4 x ~3 ms. **Local
numbers under-report per-hop cost by ~60x.**

LAN benches (G6) need physical hardware. `loopback_aliased` solves
the gap on a single machine, free, by exploiting the kernel's
loopback-address routing rules.

### 11.2 Mechanism

When uvicorn binds `0.0.0.0:8001` and a client posts to
`http://127.0.0.20:8001/invoke`, the kernel does a route lookup,
delivers the packet via the `lo` interface, and uvicorn accepts on
the `0.0.0.0` socket:

```
client(127.0.0.10) -> kernel route lookup -> lo interface ->
kernel deliver to listener on 0.0.0.0:8001 -> uvicorn accepts ->
... pydantic, @logger, sem, payload-touch, dispatch ...
```

vs the `local` fast path:

```
client(127.0.0.1) -> kernel detects same-address fast path ->
direct socket-buffer copy -> uvicorn accepts on 127.0.0.1:8001 ->
... same pydantic, @logger, sem, payload-touch, dispatch ...
```

The fast path saves the kernel routing layer + a couple of socket
state lookups. The savings is ~50-200 us of the calibration's 3 ms
loopback floor; `loopback_aliased` mode exposes it.

### 11.3 What `loopback_aliased` does NOT add (caveat)

- **NIC latency** (PCIe + driver + DMA): real wired-Ethernet adds
  ~5-30 us per packet on top.
- **Switch fabric latency**: a managed switch adds ~5-20 us.
- **Real bandwidth ceiling**: loopback throughput is RAM-bandwidth-
  bound (10+ GB/s); a 1 Gb/s NIC caps at ~125 MB/s. For 128 kB
  payloads at saturation, this matters.

So `loopback_aliased` is **honest about per-hop floor** but **not
honest about saturation behaviour**. The full LAN bench (G6) is
still required for the saturation story. Documented in CLAUDE.md so
the audit trail does not claim more than the data supports.

### 11.4 The 3-mode mental model

After this plan ships, `experiment.json::deployment` has three crisp
meanings, **strictly increasing in latency floor**:

| Mode | What it measures | When to use it |
|---|---|---|
| **`local`** | Pure software stack cost. Single Python process; `127.0.0.1` fast path; no routing layer. Calibration loopback floor: ~3 ms today. | Dev loop, fastest iteration. CI default. Canonical reference for "what does my software cost without any network". |
| **`loopback_aliased`** | Software stack + kernel routing layer + lo interface, all on one machine. Each bucket on a distinct `127.0.0.X`. Loopback floor: ~3 ms + 50-500 us. | Honest single-host bench. The default for case-study runs that don't have access to a second machine. |
| **`remote`** | Real LAN. Multiple machines, real NICs + switch + cables. Loopback floor: ~3 ms + 50-500 us + ~10-50 us hardware. | Final dissertation numbers. Run on G6 hardware. |

The three modes are **monotonic** in latency floor. A measurement in
`local` is a lower bound on the real cost; `loopback_aliased` lifts
it toward reality without buying hardware; `remote` is the
ground-truthing run that the case study presents as the headline.

### 11.5 Gates (folded into the existing G1-G7 sequence)

No new gates. The 3-mode enum and `127.0.0.10/20/30` defaults ship in
**G1** (JSON edit). The enum check (`local` short-circuit vs the
shared resolution path for the other two) ships in **G2**. The bench
in `loopback_aliased` mode ships as a sub-step of G6 (single-host
warm-up) BEFORE the LAN smoke (3-machine deployment), so honest
single-host numbers are available even if hardware procurement
delays the LAN smoke.

### 11.6 Risks specific to loopback aliases

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Aliases not pre-configured on every Windows / Linux build | Low | Medium | `127.0.0.0/8` is fully addressable on every modern OS by default; no `ifconfig add` step needed. Smoke-test on `DESKTOP-INKGBK6` at G3; if it fails, document the one-line OS prep step in `notes/quickstart.md`. |
| Some kernels MIGHT optimise cross-alias loopback so the floor never lifts | Medium | Medium | Measure: run calibration in `loopback_aliased` mode and compare the loopback floor to `local`. If they're identical, the kernel optimised it; if `loopback_aliased` is 50-200 us higher, the routing layer is engaged. The bench is the verification. |
| Operators conflate `loopback_aliased` numbers with LAN numbers | Medium | High | CLAUDE.md, the notebook prose, and the result envelope's `network.transport` block all label the deployment mode explicitly. Every persisted JSON carries `network.transport = "loopback_aliases"` so a stale grep tells you which medium produced the numbers. |
| Calibration was benched with `local` mode (`127.0.0.1`); the `loopback_aliased` floor is different | High | Low (this is what we want to measure) | Re-run calibration in `loopback_aliased` mode; persist as a sibling envelope `<host>_<ts>_loopback_aliased.json`. Apply each calibration to the runs that produced it. The two floors stand side-by-side in the dissertation. |
| `hosts` defaults of `127.0.0.10/20/30` look surprising vs `127.0.0.1` | High | Low | Comment the JSON values inline AND in CLAUDE.md. The `network.notes` field makes the why obvious in every result file. |

## 12. Follow-up: UDS transport (Path C from the mu=1600 discussion)

**Defer until distribution lands.** Once the client / TAS / atomic services run on separate hosts (Sections 1-11 done), the local-only intra-machine paths are the natural place to swap TCP loopback for Unix Domain Sockets:

```python
uvicorn.run(app, uds="/tmp/vernier.sock")
```

### 12.1 Motivation

The Cámara canonical artifacts include nodes with `mu = 1580 req/s` (`AS_{3}`) and `mu = 880 req/s` (`MAS_{4}`). The current single-host calibration on `DESKTOP-INKGBK6` (Windows + uvicorn over TCP loopback) caps per-worker throughput at `~290 req/s` because `loopback.median ~= 3 ms`. This forces the specs layer to bin-pack each artifact into multiple physical workers (`c x mu_per_worker >= mu_camara`), which:

- Couples the dimensional analysis's per-server `mu` to the host's transport ceiling, NOT the artifact's mathematical claim.
- Shifts every M/M/1/K artifact into an M/M/c queue with different latency distribution; the analytic / stochastic / dimensional methods predict M/M/1 dynamics, the experiment delivers M/M/c.
- Makes the artifact-vs-specs drift on `mu_per_worker` LARGE (often > 5x), which can swamp the DASA coefficients of interest under "host overhead, not application behaviour".

UDS lifts the loopback floor to `~400-700 us` (one-shot HTTP round trip on a Unix socket); combined with a Starlette + orjson handler stack (Path B from the same discussion), per-request latency drops to `~500 us`, giving `mu_per_worker ~= 2000 req/s`. That is enough to deliver `AS_{3}` (1580) directly with `c=1`, removing the bin-packing distortion from the dimensional analysis.

### 12.2 Blocker on this host

uvicorn's UDS code path requires `AF_UNIX`, which is **not available on Windows** (Windows has named pipes, NOT POSIX UDS, and uvicorn doesn't bridge them). Implementation needs **WSL2 or a Linux machine**. Once the distribution work targets Linux for the deployable nodes, UDS becomes a near-zero-cost upgrade on every same-host pair (e.g. when a TAS composite and one of its atomic targets land on the same node).

### 12.3 Scope (separate PR, after `distribute` ships)

In scope:

1. **Transport selector** alongside the existing `network.transport` enum (`local` / `loopback_aliased` / `lan`): add `uds` as a fourth mode for same-host hops.
2. **`hosts` schema extension**: per-role + per-pair entries can be `unix:///tmp/<role>.sock` instead of an `ip:port`.
3. **uvicorn launch path**: branch on the URL scheme. TCP for `http://...`, UDS for `unix://...`. uvicorn already supports both via `host=` / `uds=` kwargs.
4. **httpx client path**: build the `AsyncClient` with `transport=httpx.AsyncHTTPTransport(uds="/tmp/vernier.sock")` when the resolved URL is `unix://`. httpx supports this natively.
5. **Calibration variant**: run `calibration.run()` once per transport on the Linux host. Persist as a sibling envelope `<host>_<ts>_uds.json`. Compare `loopback.median_us` between TCP-loopback, UDS, and `loopback_aliased`. The three floors stand side-by-side in the dissertation as the transport-overhead axis.
6. **Specs revisit**: with `mu_per_worker ~= 2000` available, optionally collapse the bin-packed specs (`c=8 mu=250`) back to the artifact-canonical (`c=1 mu=1580`) on heavy nodes — restores the M/M/1/K dynamics the model expects.

Out of scope (still):

- Path B alone (Starlette + orjson on Windows-TCP) — half the gain at half the work; only worth doing if WSL2 is unavailable.
- Replacing FastAPI with a custom ASGI app — Path B already does the bulk of the slimming.
- Cross-host UDS — UDS is local-only by design; LAN hops stay on TCP.

### 12.4 Acceptance signals

- Linux + UDS calibration shows `loopback.median_us < 1000`.
- `derive_calib_coefs` per-worker `mu_req_per_s` reads `>= 1500`.
- Same-host experiment runs over UDS hit at least 1500 req/s sustained throughput per atomic without bin-packing (specs.c=1 reproduces artifacts.c=1).
- Cross-host (LAN) hops continue using TCP; the transport selector picks UDS only when both endpoints resolve to the same host.

### 12.5 Order of work

1. Land Sections 1-11 of `distribute.md` (per-role hosts + 3-mode transport + LAN bench).
2. Move dev to WSL2 / a Linux box for the UDS work; Windows stays as the secondary platform.
3. Land UDS as additive (TCP path stays default for backward compatibility on Windows).
4. Re-run calibration in UDS mode; persist a sibling envelope.
5. Re-run the experiment method in UDS mode against artifact-canonical specs (no bin-packing); compare against the bin-packed numbers from the Windows runs to quantify the transport-vs-bin-packing gap.

This unblocks the dissertation question "where does the model break in deployment?" with a clean per-server `mu` axis instead of a bin-packing artefact.
