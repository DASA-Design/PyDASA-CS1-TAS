# CS-01 Tele Assistance System — Summary

Every row below cites the section of [notes/cs_context.md](notes/cs_context.md) that backs it. Use this summary as the index; use `cs_context.md` for the detail, ADRs, and references.

| Field | Value | Source |
|---|---|---|
| Case ID | CS-01 | [introduction](notes/cs_context.md#introduction) |
| Case name | Tele Assistance System (TAS) | [§ CS-1 Tele Assistance System (TAS)](notes/cs_context.md#cs-1-tele-assistance-system-tas) |
| Domain | Healthcare (chronic-disease home care), service-based self-adaptive systems | [§ CS-1 intro](notes/cs_context.md#cs-1-tele-assistance-system-tas) |
| Primary source | Weyns & Calinescu, *SEAMS 2015* [1] | [Source of information](notes/cs_context.md#source-of-information) |
| Supporting sources | Iftikhar & Weyns 2014, 2017 [2][3]; Weyns & Iftikhar 2016 [13]; Cámara et al. 2023 [10] | [Source of information](notes/cs_context.md#source-of-information) |
| Runtime platform | ReSeP (Research Service Platform) | [Target System](notes/cs_context.md#target-system) |
| Adaptation engine | ActivFORMS (Active Formal Models) | [Controller](notes/cs_context.md#controller) |
| Focus scenarios | S1 service failure, S2 response-time variability | [Adaptation scenarios (Table I)](notes/cs_context.md#technical-specifications) |
| Adaptation strategies | Retry, Select Reliable | [Adaptation strategies evaluated on TAS](notes/cs_context.md#controller) |
| Variation points | `MAX_TIMEOUTS`, `timeout length`, service-catalogue size, adaptation-strategy selection | [ADR-CS1-06 + Cámara 2023 framing](notes/cs_context.md#design-notes) |
| QA lens | Performance vs. Availability | [Insights and Limitations](notes/cs_context.md#insights-and-limitations) |
| Validation targets (Cámara 2023) | R1 fail-rate ≤ 0.03 %, R2 resp-time ≤ 26 ms, R3 minimise cost s.t. R1 ∧ R2 | [Quantitative targets](notes/cs_context.md#technical-specifications) |

## Headline finding to reproduce

Table IV of [1], six-step experiment on scenario S1 (full reproduction of numbers, sample sizes, and caveats in [Headline results](notes/cs_context.md#technical-specifications)):

| Strategy | Failure rate | Sequence failure rate | Cost | Invocations |
|---|:-:|:-:|:-:|:-:|
| No Adaptation | 0.18 | 0.22 | 8.12 K | 1 561 |
| Retry | 0.11 | 0.13 | 9.95 K | 1 981 |
| Select Reliable | 0.00 | 0.00 | 11.04 K | 1 984 |

Select Reliable eliminates observed failures at ~36 % higher cost than No Adaptation; Retry halves the failure rate at ~22 % higher cost. Neither dominates — the choice depends on the utility function. See [Insights and Limitations](notes/cs_context.md#insights-and-limitations) for the analytical generalisation (per Rico) and [Design Notes](notes/cs_context.md#design-notes) for the ADR chain.

## Service catalogue (7-service baseline)

From [§ Services, Profiles, and Costs](notes/cs_context.md#target-system), Table III of [1]:

| Service | Failure rate | Cost per invocation |
|---|:-:|:-:|
| Alarm Service 1 (AS_1) | 0.11 | 4.87 |
| Alarm Service 2 (AS_2) | 0.04 | 9.74 |
| Alarm Service 3 (AS_3) | 0.18 | 2.65 |
| Medical Analysis Service 1 (MAS_1) | 0.12 | 4.43 |
| Medical Analysis Service 2 (MAS_2) | 0.07 | 7.84 |
| Medical Analysis Service 3 (MAS_3) | 0.18 | 2.78 |
| Drug Service 1 (DS_3) | 0.06 | 10.00 |

An intermediate 15-service profile ([Intermediate profile, Weyns & Iftikhar 2016](notes/cs_context.md#target-system)) and a revised 9-service profile ([Alternative service profile, Cámara 2023](notes/cs_context.md#target-system)) are catalogued but not consumed by this repo's baseline.

## What this repo produces

- `data/results/<method>/<adaptation>/<profile>.json` — PyDASA Variable-dict with measured metrics per node and network-level aggregates
- `data/results/<method>/<adaptation>/requirements.json` — R1/R2/R3 pass/fail verdict
- `assets/img/<method>/<adaptation>/*.{png,svg}` — figures cited in reports

## Pointers

- Full case record — architecture, ADRs, inconsistency table, references: [notes/cs_context.md](notes/cs_context.md)
- Condensed narrative (what to read first): [notes/cs_objective.md](notes/cs_objective.md)
- Method-by-method contracts and the 20-run matrix: [notes/workflow.md](notes/workflow.md)
- Setup and CLI: [notes/quickstart.md](notes/quickstart.md)
- Command cheatsheet: [notes/commands.md](notes/commands.md)
- Decision log: [notes/devlog.md](notes/devlog.md)

## References

Only the works cited in this summary. Full CS-1 reference list (plus ADR sources, inconsistency notes, and supporting works) in [notes/cs_context.md § References](notes/cs_context.md#references).

[1] D. Weyns and R. Calinescu, "Tele Assistance: A Self-Adaptive Service-Based System Exemplar," in *Proceedings of the 10th International Symposium on Software Engineering for Adaptive and Self-Managing Systems (SEAMS 2015)*, Florence, Italy, May 2015, pp. 88-92. doi: 10.1109/SEAMS.2015.27.

[2] M. U. Iftikhar and D. Weyns, "ActivFORMS: Active Formal Models for Self-Adaptation," in *Proceedings of the 9th International Symposium on Software Engineering for Adaptive and Self-Managing Systems (SEAMS 2014)*, Hyderabad, India, Jun. 2014, pp. 125-134. doi: 10.1145/2593929.2593944.

[3] M. U. Iftikhar and D. Weyns, "ActivFORMS: A Runtime Environment for Architecture-Based Adaptation with Guarantees," in *Proceedings of the 2017 IEEE International Conference on Software Architecture Workshops (ICSAW)*, Gothenburg, Sweden, Apr. 2017, pp. 278-281. doi: 10.1109/ICSAW.2017.21.

[9] S. Rico, "Insights Towards Better Case Study Reporting in Software Engineering," in *Proceedings of the 1st IEEE/ACM International Workshop on Methodological Issues with Empirical Studies in Software Engineering (WSESE '24)*, Lisbon, Portugal, Aug. 2024, pp. 76-79. doi: 10.1145/3643664.3648208.

[10] J. Cámara, R. Wohlrab, D. Garlan, and B. Schmerl, "ExTrA: Explaining architectural design tradeoff spaces via dimensionality reduction," *Journal of Systems and Software*, vol. 198, p. 111578, Apr. 2023. doi: 10.1016/j.jss.2022.111578.

[13] D. Weyns and M. U. Iftikhar, "Model-based Simulation at Runtime for Self-adaptive Systems," in *2016 IEEE International Conference on Autonomic Computing (ICAC)*, Würzburg, Germany, Jul. 2016, pp. 364-373. doi: 10.1109/ICAC.2016.67.
