# Case study — CS-1 Tele Assistance System (TAS)

DASA evaluation case for a service-based self-adaptive system in the chronic-disease home-care domain. *TAS* is a published reference exemplar (Weyns & Calinescu, SEAMS 2015) that orchestrates three atomic services (*Drug*, *Medical Analysis*, *Alarm*) via a *MAPE-K* loop over its composite service. Selected as CS-1 because it offers the richest QoS structure in the SAS literature and a clean managed/managing subsystem split. The companion *Smart City IoT-SDP* case lives in the sibling `PyDASA-CS2-IoT-SDP` repo.

## Identity

| Field | Value |
|---|---|
| Case identifier | `CS-1` (legacy `N1-TAS`) |
| Domain | Healthcare (chronic-disease home care); Service-Based + Self-Adaptive Systems |
| Primary source | Weyns & Calinescu (2015) [1] |
| Supporting | Iftikhar & Weyns (2014, 2017) [2], [3]; Weyns & Iftikhar (2016) [13]; Cámara et al. (2023) [10] |
| Runtime platform | *ReSeP* (Research Service Platform) [1] |
| Adaptation engine | *ActivFORMS* (Active Formal Models) [2], [3] |
| ACS designation | Descriptive with Explanatory extension (Runeson & Höst [4]) |
| QA lens | *Performance vs. Availability* (re-reading the authors' *Reliability vs. Cost* framing without changing numbers) |

## Workflow

The composite service runs an analyse-and-act pattern. Each vital-parameters message is sent to *Medical Analysis*, which returns one of three verdicts that branch to `changeDrug`, `changeDose`, or `sendAlarm` against *Drug* or *Alarm*. A panic-button press skips the analysis and calls `triggerAlarm` directly. Three decision points open non-trivial failure paths.

```
loop:
    pick task
    if task = vitalParamsMsg:
        result = MedicalAnalysisService.analyseData(data)
        if result = changeDrug:    DrugService.changeDrug(patientId)
        elif result = changeDose:  DrugService.changeDose(patientId)
        elif result = sendAlarm:   AlarmService.sendAlarm(patientId)
    elif task = buttonMsg:
        AlarmService.triggerAlarm(patientId)
```

Stochastic user model from [13]: each tick fires `p_ANALYSIS` (vital-params) or `p_EMERGENCY = 1 − p_ANALYSIS`; a typical setting is `p_EMERGENCY = 0.25`. Of non-`patientOK` analyses, ~66 % route to *Drug*, ~34 % to *Alarm*.

## Service catalogue (7-service baseline, Table III of [1])

| Service | Failure rate | Cost / invocation |
|---|:-:|:-:|
| Alarm Service 1 (AS_1) | 0.11 | 4.87 |
| Alarm Service 2 (AS_2) | 0.04 | 9.74 |
| Alarm Service 3 (AS_3) | 0.18 | 2.65 |
| Medical Analysis Service 1 (MAS_1) | 0.12 | 4.43 |
| Medical Analysis Service 2 (MAS_2) | 0.07 | 7.84 |
| Medical Analysis Service 3 (MAS_3) | 0.18 | 2.78 |
| Drug Service 1 (DS_1) | 0.06 | 10.00 |

The cost-reliability inversion is deliberate: cheap services have higher failure rates so the adaptation engine must arbitrate between *Cost* and *Reliability* rather than pick a dominant service. [13] adds a 15-service catalogue with per-service queue-length + response-time columns. [10] adds a 9-service catalogue with explicit failure-rate (%) and response-time (ms) columns and two architectural variants *V1* / *V2*. Any analysis citing TAS service parameters must state which profile (2015 / 2016 / 2023; if 2023, V1 or V2).

## Adaptation strategies

| Strategy | Mechanism | Bass tactics (3rd ed.) |
|---|---|---|
| *Retry* | On failure, select alternative from `ServiceCache` and retry; bounded count | Composition: `Exception` (detection) + `Removal from Service` + `Dynamic Lookup` |
| *Select Reliable* | Invoke equivalent service in parallel; one success suffices | `Active Redundancy` |

Both rely on stateless atomic services so parallel / retried invocations stay safe.

## Adaptation scenarios (Table I of [1])

| ID | Trigger | Adaptation type | Targets |
|:-:|---|---|---|
| `S1` | Service failure | Switch to equivalent / parallel invoke | *Reliability*, *Cost* |
| `S2` | Response-time variability | Switch to equivalent / parallel invoke | *Performance*, *Cost* |
| `S3` | New service discovered | Include new service | *Reliability*, *Performance*, *Cost* |
| `S4` | New goal | Workflow architecture change | *Functional* |
| `S5` | Wrong operation sequence | Workflow architecture change | *Functional* |

`S1` and `S2` carry quantified targets and stay within the published `WorkflowProbe`/`WorkflowEffector` set; `S4` and `S5` would require a workflow-rewriting effector that [1] does not document. This evaluation focuses on `S1` + `S2`.

## Validation criteria (Cámara et al. 2023, Table 1b of [10])

| Id | Description |
|:-:|---|
| `R1` | average failure rate ≤ `0.03%` |
| `R2` | average response time ≤ `26 ms` |
| `R3` | subject to R1 and R2, minimise cost |

`R3` is a **conditional optimisation** — cost minimisation only meaningful when R1 and R2 hold simultaneously. The earlier [13] framing used different targets (`failureRate ≤ 0.15 × 10⁻³`, `averageCost ≤ 8 × 10⁻³`) and **inverted** the R3 objective (minimise failure rate, not cost). Any comparison must declare which framing it uses.

## Headline finding (Table IV of [1], scenario S1)

| Strategy | Failure rate | Sequence failure rate | Cost | Invocations |
|---|:-:|:-:|:-:|:-:|
| *No Adaptation* | 0.18 | 0.22 | 8.12 K | 1 561 |
| *Retry* | 0.11 | 0.13 | 9.95 K | 1 981 |
| *Select Reliable* | 0.00 | 0.00 | 11.04 K | 1 984 |

*Select Reliable* eliminates observed failures at ~36 % higher cost than *No Adaptation*; *Retry* halves the failure rate at ~22 % higher cost. Neither dominates — the choice depends on the *Reliability*-vs-*Cost* utility function. A zero-failure rate over 500 messages is not the same as zero failure probability; [13] §V-B extends the run to 10 000 invocations.

## Architectural decisions

- **ADR-CS1-01** Adopt *TAS* as CS-1 (richest QoS, clean managed/managing split, broad adoption). CS-2 is *IoT-SDP* (different structural features).
- **ADR-CS1-02** Focus analytical work on `S1` and `S2`; `S3`-`S5` documented but not quantified.
- **ADR-CS1-03** Adopt [1] Table IV as the comparison baseline; [13] §V-B as extended-sample-size complement. We re-interpret published results, not re-run experiments.
- **ADR-CS1-04** Preserve stateless atomic services for *Select Reliable* semantics.
- **ADR-CS1-05** Document both abstraction levels (composite-to-atomic and atomic-to-atomic peer substitution) as separate views.
- **ADR-CS1-06** [1] is the authoritative source. [2] / [3] cited only for *ActivFORMS* engine semantics. [13] is a mid-generation complement (stochastic user model, 15-service catalogue, service-time decomposition). [10] is a second-generation analytical revision (9-service catalogue, V1/V2, revised R1/R2/R3). Where [13] and [10] disagree, both framings are quoted explicitly.

Inconsistencies between [1] / [13] / [10] (service count, naming, failure-rate units, R3 inversion, target values, V1/V2 split) are catalogued in [`__OLD__/notes/context.md`](../__OLD__/notes/context.md) §"Inconsistencies noted across source documents".

## Self-* properties exercised (per IBM autonomic taxonomy)

- **Self-Healing** — `WorkflowProbe.serviceFailed` discovers failures; `WorkflowEffector.setPreferredService` swaps in alternatives.
- **Self-Optimization** — Planner utility function trades response time, failure rate, cost.
- **Self-Awareness** — probes monitor the four QAs / three requirements continuously.
- **Context-Awareness** — `ServiceCache` tracks external-provider metrics so adaptation depends on environment state.

## Validity (Runeson-Höst dimensions)

- **Construct** — *Reliability* counts raw failed invocations; sequence failures may compound. The Bass tactic mapping is interpretive (only tactics verbatim from [6]).
- **Internal** — [1] runs 500 messages per strategy with slight invocation-count differences; perfect-reliability claims read as "no failure observed in this run", not "zero probability".
- **External** — In scope: SBS with composite workflow, replaceable atomic services with quantified QoS, MAPE-K loop. Out of scope: stateful, event-driven, or safety-critical systems.
- **Reliability of replication** — [1] code, profiles, and UPPAAL models are public; the random-number seed is not stated.

## References

[1] D. Weyns and R. Calinescu, "Tele Assistance: A Self-Adaptive Service-Based System Exemplar," *SEAMS 2015*, pp. 88-92. doi: 10.1109/SEAMS.2015.27.
[2] M. U. Iftikhar and D. Weyns, "ActivFORMS: Active Formal Models for Self-Adaptation," *SEAMS 2014*, pp. 125-134. doi: 10.1145/2593929.2593944.
[3] M. U. Iftikhar and D. Weyns, "ActivFORMS: A Runtime Environment for Architecture-Based Adaptation with Guarantees," *ICSAW 2017*, pp. 278-281. doi: 10.1109/ICSAW.2017.21.
[4] P. Runeson and M. Höst, "Guidelines for conducting and reporting case study research in software engineering," *EMSE*, vol. 14, no. 2, 2009. doi: 10.1007/s10664-008-9102-8.
[6] L. Bass, P. Clements, and R. Kazman, *Software Architecture in Practice*, 3rd ed., 2012.
[8] C. Wohlin, "Case Study Research in Software Engineering: It is a Case, and it is a Study, but is it a Case Study?," *IST*, vol. 133, 2021. doi: 10.1016/j.infsof.2021.106514.
[9] S. Rico, "Insights Towards Better Case Study Reporting in Software Engineering," *WSESE 2024*, pp. 76-79. doi: 10.1145/3643664.3648208.
[10] J. Cámara, R. Wohlrab, D. Garlan, and B. Schmerl, "ExTrA: Explaining architectural design tradeoff spaces via dimensionality reduction," *JSS*, vol. 198, 2023. doi: 10.1016/j.jss.2022.111578.
[12] C. Krupitzer et al., "A survey on engineering approaches for self-adaptive systems," *PMC*, vol. 17, 2015. doi: 10.1016/j.pmcj.2014.09.009.
[13] D. Weyns and M. U. Iftikhar, "Model-based Simulation at Runtime for Self-adaptive Systems," *ICAC 2016*, pp. 364-373. doi: 10.1109/ICAC.2016.67.

Full source-by-source ADR provenance, the validity-threats table, and the cross-source inconsistency table preserved at [`__OLD__/notes/context.md`](../__OLD__/notes/context.md).
