# Summary — Denning & Buzen (1978), *The Operational Analysis of Queueing Network Models*

*Computing Surveys 10(3), pp. 225–261*

This tutorial introduces **operational analysis**: a framework in which every variable is a directly measurable quantity over a finite observation period, and every law is an identity that must hold in any such period. It is the operational counterpart of Markovian queueing theory and was developed because stochastic assumptions (steady state, ergodicity, Poisson arrivals, exponential service, independence) are *not* testable on real systems, whereas operational assumptions are.

---

## 1. Basic operational variables (single-server, Fig. 1)

Over an observation period of length `T`:

| Symbol | Meaning | Definition |
|---|---|---|
| `T` | length of observation period | measured |
| `A` | number of arrivals | measured |
| `B` | busy time (`B ≤ T`) | measured |
| `C` | number of completions | measured |
| `λ = A/T` | arrival rate | derived |
| `X = C/T` | output rate (throughput) | derived |
| `U = B/T` | utilisation | derived |
| `S = B/C` | mean service time per completion | derived |

### Utilisation Law (operational identity)
**`U = X · S`**
Holds in *every* observation period, no assumption required.
*Example:* `X = 3 jobs/s`, `S = 0.1 s/job` ⇒ `U = 0.30`.

### Job-Flow-Balance Assumption
**`A = C`** ⇒ **`λ = X`** ⇒ **`U = λ·S`**
Testable; holds approximately when `(A − C)/C` is small.

---

## 2. Multi-device network quantities (Figs. 4–8)

For `K` devices, `N` jobs, device `i`:

- `A_i`, `B_i`, `C_i` — per-device arrivals, busy time, completions
- `C_{ij}` — count of jobs going from device `i` to device `j`
- `U_i = B_i/T` — utilisation of device `i`
- `S_i = B_i/C_i` — mean service time at device `i`
- `X_i = C_i/T` — completion rate at device `i`
- `q_{ij} = C_{ij}/C_i` — **routing frequency** (fraction of completions at `i` proceeding to `j`); `q_{i0} = C_{i0}/C_i` (exit); `q_{0j} = A_{0j}/A_0` (entry)
- `X_0 = C_0/T` — system throughput
- `n_i(t)` — queue length at device `i` (includes the one in service)
- `W_i = ∫ n_i(t) dt` — area under the `n_i(t)` curve (job-seconds)
- `n̄_i = W_i/T` — mean queue length
- `R_i = W_i/C_i` — mean response time at device `i`

### Little's Law (per device)
**`n̄_i = X_i · R_i`**
*Example (Fig. 8, T=20 s, B=16, C=10):* `U=0.80`, `S=1.6 s`, `X=0.5 jobs/s`, `W=40 job-s`, `n̄=2 jobs`, `R=4 s`.

---

## 3. Job-flow analysis (§4)

### Job-Flow-Balance Equations
**`X_j = Σᵢ Xᵢ · qᵢⱼ`**, `j = 0, …, K`
(`K+1` equations, one dependent, so `K` independent.)

### Visit ratio
**`V_i = X_i / X_0`** — mean number of visits to device `i` per system completion.

### Forced Flow Law
**`X_i = V_i · X_0`**
Flow anywhere determines flow everywhere.
*Example:* If each job generates 5 disk requests and disk throughput is 10 req/s, then `X_0 = 10/5 = 2 jobs/s`.

### Visit Ratio Equations
**`V_0 = 1`**, **`V_j = q_{0j} + Σᵢ Vᵢ · qᵢⱼ`**
For a central-server network: `V_1 = 1/q_{10}`, `V_i = q_{1i}/q_{10}` for `i ≥ 2`.

### General Response Time Law (applying Little's Law to the whole system)
**`R = N̄ / X_0 = Σᵢ Vᵢ · Rᵢ`**

### Interactive Response Time Formula (terminal-driven, Fig. 6)
**`R = M/X_0 − Z`**
where `M` = terminals, `Z` = think time.
*Example 1 (§4 Examples):* 25 terminals, `Z=18 s`, disk `U=0.5`, 20 disk req/job, `S=0.025 s/req`.
`X_0 = Uᵢ/(Vᵢ·Sᵢ) = 0.5/(20·0.025) = 1 job/s`; `R = 25/1 − 18 = 2 s`.

---

## 4. Bottleneck analysis (§4, asymptotic)

Under invariance of `Vᵢ`, `Sᵢ`:

- **Bottleneck `b`:** the device with **`V_b S_b = max{V₁S₁, …, V_K S_K}`**.
- **Saturation throughput:** **`X_0 → 1/(V_b S_b)`** as `N → ∞`.
- **Minimum response time** (no queueing, `N=1`): **`R_0 = Σᵢ Vᵢ Sᵢ`**.
- **Saturation point** (closed system): **`N* = R_0 / (V_b S_b)`**.
- **Terminal-driven saturation** (terminals above which central subsystem saturates): **`M_b* = (R_0 + Z)/(V_b S_b) = N* + Z/(V_b S_b)`**.
- Large-`M` response-time asymptote: **`R ≈ M · V_b S_b − Z`**; x-intercept at `M_b = Z/(V_b S_b)`.

*Example (Fig. 11, §4 Example):* `V=(20,11,8)`, `S=(0.05,0.08,0.04)` → `V_iS_i = (1.00, 0.88, 0.32)` s. `R_0 = 2.2 s`, CPU is bottleneck (`b=1`). `M_1 = Z/V_1S_1 = 20` terminals, `N* = R_0/V_1S_1 = 2.2` jobs, `M_1* = 22.2`. A 7% faster CPU (`S_1' ≤ 0.047 s`) meets `R ≤ 8 s` at `M=30`; no CPU speedup can meet `R ≤ 10 s` at `M=50` because the disk then becomes the limit.

---

## 5. Load-dependent behaviour (§5)

Replace invariance with **conditional invariance** indexed by local queue length `n`:

- `Cᵢⱼ(n)`, `Tᵢ(n)` — counts/time conditioned on `nᵢ = n` (stratified sampling)
- **Service function:** **`Sᵢ(n) = Tᵢ(n) / Cᵢ(n) = 1/Xᵢ(n)`** — mean inter-completion time when queue is `n`
- **Queue-length distribution:** **`pᵢ(n) = Tᵢ(n)/T`**
- `n̄ᵢ = Σₙ₌₁^∞ n·pᵢ(n) = Wᵢ/T`

*Example (Fig. 14):* device serves 4 jobs for 4 s each at arrivals `t=0,1,2,3`. `S = 4 s` unconditional, but `p(0)=0`, `p(n)=5/16` for `n=1..3`, `p(4)=1/16`. `n̄ = 2.125` jobs, `R = 8.5 s`. Same service demand, very different queueing behaviour depending on arrival pattern.

---

## 6. State-space analysis and product form (§6)

State vector **`n = (n₁, …, n_K)`**, `N = Σnᵢ`. Number of states in a closed system: **`L = (N+K−1)! / (N!(K−1)!)`**.

### State-Space Balance Equations
**`Σ_k p(k)·r(k,n) = p(n)·Σ_m r(n,m)`** for every state `n`, with `Σ p(n) = 1`.
Where `r(n,m) = C(n,m)/T(n)` is the transition rate.

### Two operational assumptions (testable):
1. **One-step behaviour:** only single-job transitions observed (reduces `L²` rates to `~LK²`).
2. **Homogeneity:**
 - *Device homogeneity:* `Sᵢ(n)` depends only on `nᵢ`, not on the global state.
 - *Routing homogeneity:* `qᵢⱼ` depends only on total load `N`, not on local queues.

These replace Markovian assumptions (exponential service, Poisson arrivals, ergodicity) and yield the same solution.

### Product-Form Solution
**`p(n) = F₁(n₁)·F₂(n₂)···F_K(n_K) / G`**
where
**`Fᵢ(n) = 1` if `n=0`, else `Fᵢ(n) = Xᵢ · Sᵢ(n) · Sᵢ(n−1) ··· Sᵢ(1)`**
and `G = Σ_{Σnᵢ = N} F₁(n₁)···F_K(n_K)` is the normalising constant.

### Homogeneous Service Times (HST) simplification
If `Sᵢ(n) = Sᵢ` (constant), then `Fᵢ(n) = (VᵢSᵢ)ⁿ` (closed) or `Fᵢ(n) = Uᵢⁿ` (open).
*HST Jackson/open result:* `pᵢ(n) = (1 − Uᵢ) Uᵢⁿ` per device, independent.
HST typically gives utilisations within 10% and queue lengths within ~30%.

---

## 7. Buzen's convolution algorithm for `G` (§7)

For a closed HST system, compute **`g(n,k)`** in a `(N+1)×K` matrix:

**`g(n,k) = g(n, k−1) + Yₖ · g(n−1, k)`**, with `Yₖ = Vₖ Sₖ`, `g(0,k)=1`, `g(n,0)=0` for `n>0`.

Cost: **`2KN`** operations. `G = g(N,K)`.

Performance quantities as closed-form ratios:

| Quantity | Formula |
|---|---|
| Proportion of time `nᵢ ≥ n` | `Qᵢ(n) = Yᵢⁿ · g(N−n, K) / g(N, K)` |
| Utilisation | `Uᵢ = Qᵢ(1) = Yᵢ · g(N−1, K) / g(N, K)` |
| System throughput | `X_0 = g(N−1, K) / g(N, K)` |
| Mean queue length | `n̄ᵢ = Σₙ₌₁^N Yᵢⁿ · g(N−n, K) / g(N, K)` |
| Recursion | `n̄ᵢ(N) = Uᵢ(N) · (1 + n̄ᵢ(N−1))` |

### Terminal-Driven algorithm (Fig. 18)
**`h(m,k) = h(m, k−1) + (m·Yₖ / Z) · h(m−1, k)`**
Throughput `X(M) = (M/Z)·h(M−1,K)/h(M,K)`, `R(M) = M/X(M) − Z`, `N̄ = M − Z·X(M)`.

*Example:* For Fig. 11(a) at `M=18`: `X = 0.715 jobs/s`, `R = 5.2 s`, `p(0) = 0.062`, `N̄ = 3.7` — matches bottleneck sketch.

---

## 8. Decomposition (§8)

A subsystem can be replaced by an **equivalent device** with load-dependent service function **`S(N) = 1/X(N)`**, obtained by an *offline experiment*: operate the subsystem under constant load `N`, measure its output rate `X(N) = C/T`. Exact only if the subsystem is homogeneous; a good approximation when state changes per interaction are numerous. Output rate of the enclosing system:
**`X_0(N) = Σ_n p(n)/p(N) · Σᵢ q_{i0}/Sᵢ(nᵢ)`**

Used for virtual-memory thrashing analysis, blocking, multi-level modularisation.

---

## Operational Equations Summary (Table I, p. 237)

| Law | Formula |
|---|---|
| Utilisation | `Uᵢ = Xᵢ Sᵢ` |
| Little's | `n̄ᵢ = Xᵢ Rᵢ` |
| Forced Flow | `Xᵢ = Vᵢ X_0` |
| Output Flow | `X_0 = Σᵢ Xᵢ q_{i0}` |
| General Response Time | `R = Σᵢ Vᵢ Rᵢ` |
| Interactive Response Time | `R = M/X_0 − Z` (needs flow balance) |

---

## Core message

Operational analysis gives the **same product-form solution** as Markovian theory, but under assumptions (flow balance, one-step behaviour, homogeneity) that can be **directly verified by measurement** in a finite period. This is why queueing network models predict real system performance so accurately (usually within 10% on utilisation, 30% on queue lengths) even when stochastic assumptions are clearly violated. The operational laws (`U=XS`, Little's, Forced Flow) are *identities* — failures of these reveal measurement errors, not model errors.

---

### Connection to this dissertation

This paper is the theoretical anchor for Ch05 PACS and the Ch06 PyDASA queueing walkthrough. Notably, the **`U = X·S`**, **`X_i = V_i X_0`**, and **`R = M/X_0 − Z`** identities are the same operational laws PACS relies on, and the **`V_b S_b`** bottleneck criterion parallels the saturation-limit reasoning. Denning & Buzen do *not* introduce `σ = Wλ/K` or `ρ ≤ 0.5` — those are DASA-specific dimensional results layered on top of this operational foundation.
