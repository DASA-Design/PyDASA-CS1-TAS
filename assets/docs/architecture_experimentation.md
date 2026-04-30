# Software Architecture and the Art of Experimentation

Source: Pureur, P. & Bittner, K. — *Software Architecture and the Art of Experimentation*, InfoQ, 2024-12-17. <https://www.infoq.com/articles/architecture-experimentation/>

## Core thesis

Architects will be wrong; the discipline is **bounding the cost of being wrong**. *"The art of architecting is to spend only a little bit of time going down the wrong path."* The only way to know is run experiments — but you cannot run them for everything, so the meta-skill is choosing **which** decisions to test (the architecturally fatal ones).

## The central concept: Minimum Viable Architecture (MVA)

An MVA is *"a set of decisions that you believe will make the increment of the system or product...able to sustainably deliver value over time."*

It is **not separate from the MVP** — every release is simultaneously an MVP (experiment about value) and an MVA (experiment about technical viability + supportability). Without an MVA, *"an MVP is just smoke and mirrors."*

Distinct from prototypes: MVAs are **not throwaway**.

## What "experiment" means

*"A test specifically designed to confirm or reject a particular hypothesis."* Popperian:

- Experiments **can disprove** assumptions, never prove correctness.
- "Trying something to see if it works" does not qualify — that is just trying.

## Three properties of effective architectural experiments

| Property | Meaning |
|---|---|
| **Atomic** | One question at a time; co-varying questions muddles results |
| **Timely** | Risk broken into chunks small enough to feed back fast |
| **Unambiguous** | Pre-stated success criterion, measurable outcome |

## Five things every experiment needs

1. **Clear hypothesis** — e.g. "satellite image-recognition can detect vegetation near a structure to assess fire risk"
2. **Explicit measurable goal** — operationalised: *"identify two bushes and one tree within 30 feet of a specific house"*
3. **Method + measurement mechanism** — e.g. pre-trained model output cross-checked against ground-level photos
4. **Rollback plan** — non-destructive experiments do not need one; destructive ones need version-revert / A/B / rapid-redeploy
5. **Explicit timeline** — must fit a single sprint; if not, split it

## Two case studies

### Vector DB for fraud detection (financial services)

- Hypothesis: vector DB will speed MVP delivery
- Outcome: programming paradigm mismatch + perf targets unmet
- Win: discovered in one experiment instead of mid-MVP

### Image recognition for fire-risk underwriting (insurance)

- Operationalised success as the "two bushes / one tree / 30 ft" predicate
- Used a pre-trained model (limited training scope) against satellite images

## Pitfalls

- **Extending a failed experiment** to "give it more time" — sunk-cost trap. Treat retraining/refinement as a *new* experiment with a fresh hypothesis.
- **Too many experiments** is also bad: *"if it does not matter whether a decision turns out to be wrong, that decision is not really architectural, it is simply a different design choice."*
- **Implicit assumptions are silent decisions** — every requirement, especially Quality Attribute Requirements (QARs), is a hypothesis about value. If you do not test it, you are betting on it.
- Some experiments need budget (hardware, cloud, temporary expertise) — plan for that.

## "Support and change" work — often forgotten

A good architecture anticipates change but **how do you know if it is enough?** Run experiments that **measure the cost of specific kinds of change**.

Concrete example: an insurance underwriting system covering household items + fire claims. Experiment with adding a new asset type (fine art) and a new loss type (theft) to find which changes are easy and which require a whole new system. Knowing the **boundaries of change** is itself an architectural decision (this is why homeowners policies do not cover automobiles — the asset/risk space differs too much).

## Failure-mode experiments

Architecture must also be supportable. *"When it fails does it provide enough information to diagnose the problem?"* Sometimes the only way to know is to **deliberately make the system fail** and observe what diagnostic information emerges.

LLM example: using an LLM to enter/validate insurance rules. Run experiments that **force the LLM to produce wrong outputs** before deploying — if you cannot diagnose the wrongness, reconsider the LLM approach entirely.

## Conclusion (the authors' framing)

Two-pronged discipline:

1. **Test decisions as much as possible** with experiments that challenge assumptions
2. **Construct the system so that when decisions are incorrect, failure is graceful** — enough information for support staff or future devs to fix without scrapping major parts

## How this departs from traditional architecture

| Traditional | This article |
|---|---|
| Architect assumes, decides, defends | Architect hypothesises, experiments, **falsifies** |
| Architecture is a frozen artefact | Architecture is a **continuous experiment** running inside every release |
| QARs are requirements to satisfy | QARs are **hypotheses about value** that need testing |
| "Did we deliver?" | "Did we falsify our assumptions before they hurt us?" |

## Mapping onto CS-01 TAS work

| MVA pattern from the article | CS-01 TAS analogue |
|---|---|
| Hypothesis + measurable predicate | "Does this `(c, K, mu)` combo sustain target rate?" -> `target_loss_pct <= 2.5%` (the bushes/tree predicate equivalent) |
| Atomic experiment (one question) | One sweep_grid combo per question |
| Rollback plan | `enforce_limits=False` + `K=0` sentinel preserve legacy behaviour |
| Anticipating change | Per-host calibration -> `baseline` block on every envelope so future hosts can be re-baselined without re-running the experiment |
| Failure-mode design | The K-tactic itself: rejecting at 503 instead of growing the asyncio queue is "fail gracefully with diagnostic info" |
| "MVP not throwaway" | The vernier service IS the calibration probe AND a runtime artifact reused across sweeps |

The InfoQ piece is essentially a generalisation of what `notes/calibration.md` + the experiment method are already doing operationally.

## References

- Pureur, P. & Bittner, K. (2024). *Software Architecture and the Art of Experimentation*. InfoQ, 2024-12-17. <https://www.infoq.com/articles/architecture-experimentation/>
