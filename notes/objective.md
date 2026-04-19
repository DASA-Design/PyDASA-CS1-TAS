# Case Studies

We evaluate *DASA* against two case studies: the *Tele Assistance System* (*TAS*), a service-based self-adaptive application for chronic-care home monitoring with a centralised *MAPE-K* loop over its composite service, and the *Smart City IoT Service Discovery Platform* (*IoT-SDP*), a federated peer-to-peer service register with one *MAPE-K* manager per gateway. Both are published, architecturally complete, and come with the original authors' *QA* claims, which gives external evidence beyond the PACS illustrative example.

Each case section follows the *Architectural Case Study* (*ACS*) template. The template groups content into four methodological sections: the Summary captures case identification and the bounded system; the **Technical Specifications** state the case type and research questions; the **Architectural Reconstruction** documents data-collection methods through component, scenario, and deployment views; and the *Limits*, *Insights*, and *Design Notes* cover validity threats, generalisability claims, and architectural design records.

The first subsection reconstructs *TAS*, the second reconstructs *IoT-SDP*, and the third compares them. Each case section carries a specification summary (Summary + Technical Specifications), a focused architectural reconstruction, and a short findings paragraph (Limits + Insights + Design Notes). The full reconstructions, and the *DASA* evaluation of both cases, are produced by the pipeline in this repo.

## Tele-Assistance System (TAS)

Weyns and Calinescu introduced the *Tele Assistance System* (*TAS*) in 2015 [1] as a reference exemplar for the *SAS* research community. *TAS* is a service-based self-adaptive application for chronic-disease home care, with diabetes as its canonical clinical example [2]. Two later revisions (Weyns and Iftikhar 2016 [13], Cámara et al. 2023 [10]) use different service-profile catalogues, and we cite the source paper alongside any service-specific number.

Functionally, *TAS* samples vital parameters, analyses them externally, changes the drug or dose when the analysis warrants it, and triggers an alarm either on an emergency verdict or directly through a panic-button path that bypasses the analysis. Weyns and Calinescu define five adaptation scenarios (*S1*-*S5*). *S1* (service failure) and *S2* (response-time variability) are the most thoroughly documented; only *S1* carries quantified results, in the primary paper's Table IV. The published effector set covers *S1*-*S3*; *S4* (new goal) and *S5* (wrong operation sequence) would need a workflow-rewriting effector that the paper does not document. We therefore centre the architectural reconstruction on *S1* and *S2* (the scenarios with quantified targets and published effectors) and treat *S3*-*S5* as out of scope here.

Weyns and Calinescu frame four *QAs* (*Reliability*, *Performance*, *Cost*, *Functionality*) with the primary trade-off between *Reliability* and *Cost* [1]. *Retry* and *Select Reliable* are adaptation strategies driven by the *ActivFORMS* (Active Formal Models) engine and realised as multi-step plans over one or more Bass et al. tactics. *Retry* halves the failure rate at roughly 22.0 \% higher cost than no adaptation; *Select Reliable* eliminates observed failures (in the authors' own wording, *entirely*) at roughly 36.0 \% higher cost; neither dominates. Under the *Performance vs Availability* lens, we read *Reliability* as *Availability*.

### Specification Summary

**Table 7.1: *TAS* specification summary.**[^cs1-flags]

| Attribute| Description|
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Case identifier| `CS-1`|
| Case name| *Tele Assistance System* (*TAS*) ✓|
| Domain| - Healthcare, chronic-disease home care ✓. - Service-Based Systems (*SBS*) ✓. - Self-Adaptive Systems (*SAS*) ✓.|
| Primary source| Weyns and Calinescu (2015) [1] ✓|
| Supporting sources| - Iftikhar and Weyns (2014, 2017) [2], [3] ✓. - Weyns and Iftikhar (2016) [13] ✓. - Cámara et al. (2023) [10] ✓.|
| Runtime platform| *ReSeP* (Research Service Platform) ✓|
| Adaptation engine| *ActivFORMS* (Active Formal Models) ✓|
| ACS designation| Descriptive with Explanatory extension (Runeson and Höst) ○|
| QA goals| -*R1:* failure rate ≤ 0.03 \% (*Reliability*) ✓. - *R2:* response time ≤ 26 ms (*Performance*) ✓. - *R3:* minimise cost subject to *R1* and *R2* (*Cost*) ✓. - *Functionality* ✓. |
| Architectural constraints | - Service-oriented architecture on*ReSeP* ✓. - Stateless atomic services (idempotent operations) ✓. - *ActivFORMS* adaptation with verified *UPPAAL* stochastic-timed-automata (STA) models ✓.|
| Variation points| -`MAX_TIMEOUTS` ✓. - `timeout length` ✓. - Service-catalogue size ○. - Adaptation-strategy selection ○.|
| Adaptation Scenarios| -*S1* service failure ✓. - *S2* response-time variability ✓. - *S3* new service discovered ✓. - *S4* new goal ✓. - *S5* wrong operation sequence ✓.|

Two of the variation points in Table 7.1 are our own reading rather than explicit labels. `service-catalogue size` is inferred from the fact that the catalogue expands from seven services in [1] to fifteen in [13] and nine in [10], which implies size is a tunable dimension even though none of the sources labels it as such. `adaptation-strategy selection` is the design-time choice between *Retry* and *Select Reliable*; the two strategies are named in [1] but the act of picking one over the other is not called out as a variation point.

### Architectural Reconstruction

The Target System is the *TAS* composite service, which orchestrates three atomic services (*Drug*, *Medical Analysis*, *Alarm*) for a patient's wearable device (Figure 7.1). The composite runs on the *ReSeP* (Research Service Platform), a research implementation of service-oriented principles; the Controller is a *MAPE-K* loop realised by *ActivFORMS* around the composite.

![TAS context diagram.](../../../img/07/cs1/cs_tas_context.svg)

Figure 7.1. *TAS* context diagram.

The composite follows an analyse-and-act pattern at runtime (Figure 7.2). Each vital-parameters message goes to the *Medical Analysis Service*, which returns one of three verdicts that branch to `changeDrug`, `changeDose`, or `sendAlarm` against the *Drug* or *Alarm* service. A panic-button press skips the analysis and calls `triggerAlarm` on the *Alarm* service directly. Three decision points therefore open non-trivial failure paths, and the *MAPE-K* loop must cover all of them.

![TAS workflow diagram.](../../../img/07/cs1/cs_tas_workflow.svg)

Figure 7.2. *TAS* workflow.

Five principal classes structure the managed subsystem (Figure 7.3): `CompositeService` orchestrates the workflow; `AtomicService` holds the concrete *Drug*, *Medical Analysis*, and *Alarm* instances; `ServiceRegistry` and `ServiceCache` handle runtime lookup and client-side caching; `WorkflowEngine` runs the composite's workflow specification. The decision variables for the Controller sit on each concrete atomic service: its `ServiceDescription` exposes a failure-rate and a cost-per-invocation attribute, and those attributes drive every adaptation choice.

![ReSeP service structure.](../../../img/07/cs1/cs_tas_services.svg)

Figure 7.3. *ReSeP* service structure realising the *TAS* composite service.

Two adaptation strategies ride on the Controller's feedback loop. *Retry* composes *Exception* (fault detection), *Removal from Service*, and *Dynamic Lookup*; *Select Reliable* is *Active Redundancy*, with equivalent services invoked in parallel and one success sufficient. The Controller itself observes the workflow through `WorkflowProbe` (emitting `serviceFailed` and other events) and actuates through `WorkflowEffector` (`removeFailedService`, `setPreferredService`, `changeQoSRequirement`); its loop is specified as formal models, verified at design time, and executed directly at runtime without code generation. Both strategies rely on stateless atomic services so that parallel or retried invocations remain safe.

Figure 7.4 renders the two focus scenarios in the authors' own notation. *S1* (Figure 7.4a) fires when an atomic-service invocation returns a failure verdict: the Controller flags the failing service as unavailable, and the workflow falls back to an equivalent one resolved through `ServiceRegistry`. *S2* (Figure 7.4b) fires when the moving-average response time crosses the per-scenario threshold: the Controller updates the preferred-service ranking so that subsequent invocations route to a faster equivalent. Neither scenario rewrites the workflow, which is why they stay within the published effector set.

![S1 service failure.](../../../img/07/cs1/cs_tas_sas_s1.svg)
![S2 response-time variability.](../../../img/07/cs1/cs_tas_sas_s2.svg)

Figure 7.4. *TAS* adaptation scenarios: (a) *S1* service failure and (b) *S2* response-time variability.

Four items are out of scope for this reconstruction: the remaining scenarios *S3* (new service discovered), *S4* (new goal), and *S5* (wrong operation sequence); the full tactic catalogue; the managed/managing-class split; and the formal-model set.

### Findings

Weyns and Calinescu's own analysis already exposes the central tension: *Retry* and *Select Reliable* both improve *Reliability* but neither dominates on *Cost*, and *R3* is posed as a conditional optimisation, with cost minimised only when the *R1* reliability bound and the *R2* response-time bound hold simultaneously. Under the *Performance vs Availability* lens, *R1* is an *Availability* constraint and *R2* a *Performance* constraint, so *R3* becomes a cost-minimisation surface bounded by two *QA* floors rather than a scalar objective. What [1] does not do is quantify how close the operating point sits to either bound, nor report how much additional *Cost* each percentage point of *Reliability* buys; those are the questions the DASA evaluation takes up.

## IoT Service Discovery Protocol (IoT-SDP)

Cabrera and Clarke introduced the *Smart City IoT Service Discovery Platform* (*IoT-SDP*) in 2019 [1] as a federated peer-to-peer service register for self-adaptive service discovery in large, heterogeneous, mobile urban environments. Every gateway runs its own *MAPE-K* autonomic manager over a local service register, and the gateways collectively expose a logically unified discovery surface without the bottleneck of a centralised directory. Cabrera and Clarke engineered the platform to cope with variable network conditions, rapidly changing service availability, and a mix of stationary and mobile gateways, while preserving low service-discovery latency, low network overhead, and low per-gateway resource utilisation.

Functionally, *IoT-SDP* receives discovery requests from urban entities through the service-register interface, maintains the service-descriptor register across gateways with fresh information, resolves requests locally when possible (and forwards otherwise), and reacts or proactively adapts to city events that shift the relevance of service descriptors. Cabrera and Clarke define three adaptation scenarios (*E1*-*E3*): *E1* for *Unforeseen* fires reactively through a rule-based planner, *E2* for *Scheduled* is also reactive but with the adaptation queued for a known time, and *E3* for *Periodic* fires proactively through a *Deep-Q Network* planner that learns from the slope of the utility function. We therefore centre the architectural reconstruction on *E1* and *E3*, the two extremes of the time-horizon spectrum (reactive versus proactive); *E2* is out of scope here because it is structurally a time-triggered variant of *E1*.

Cabrera and Clarke frame every *QA* concern under *Performance*, decomposing it into three sub-dimensions: *latency* (`artt`, service-discovery response time), *network overhead* (register-synchronisation traffic between gateways), and *resource utilisation* (`pust`, per-gateway CPU, RAM, buffer occupation). The sub-dimensions trade off against one another: higher replication cuts latency but raises overhead, and more frequent synchronisation improves freshness at the cost of resource utilisation. They formalise the adaptation objective as a weighted utility function over five metrics: `rsrt` (*Rate of Solved Requests*), `aspt` (*Average Search Precision*), `v(artt)` (latency variation of `artt`, *Average Response Time*), `anht` (*Average Number of Hops*), and `pust` (*Percentage of Used Storage*); it triggers reactive adaptation when utility drops below `T = 0.15`. Under the *Performance vs Availability* lens we re-read `rsrt` and `aspt` as *Availability*[^cs2-flags] signals: a stale register degrades both, so in this architecture we treat *Availability* as register freshness.

### Specification Summary

**Table 7.2: *IoT-SDP* specification **

| Attribute| Description|
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Case identifier| `CS-2`|
| Case name| *Smart City IoT Service Discovery Platform* (*IoT-SDP*) ✓|
| Domain| - Internet of Things (*IoT*) ✓. - Smart Cities ✓. - Pervasive Computing ✓. - Self-Adaptive Systems (*SAS*) ✓.|
| Primary source| Cabrera and Clarke (2019) [1] ✓|
| Supporting sources| Cabrera, Palade, White, and Clarke (2018) [2] ✓|
| Runtime platform| - Federated peer-to-peer gateways implementing the*MAPE-K* autonomic reference model ✓. - Each gateway runs Python 3.5 over a local *MongoDB 2.4* service register ✓. - *MQTT* broker for inter-gateway messaging ✓. - Testbed: `5` Raspberry Pi 3 boards (`1 GB` RAM, `16 GB` SD each) ✓. - Simulation: *Simonstrator* framework with `500` gateways across Dublin city centre (`2 km²`), Kelvin HPC cluster (`12 x 2.66 GHz` Intel processors, `24 GB` RAM per node) ✓.|
| Adaptation engine| - Mixed planner: rule-based for*E1* and *E2*, *Deep-Q Network* for *E3* ✓. - No named engine ✓.|
| ACS designation| Descriptive with Explanatory extension (Runeson and Höst) ○|
| QA goals| - *latency* (*Performance*): service-discovery response time `artt`, captured by the utility function Eq. 6 ✓. - *network overhead* (*Performance*): register-sync traffic, `~150 kB` adaptation overhead observed for *E2* and *E3* in the testbed ✓. - *resource utilisation* (*Performance*): `pust` (CPU `~25 %` on Gateway 1, per-gateway RAM, and buffer occupation) ✓. - *Availability*: register freshness, maintained by *Ping/Echo* (stationary gateways) and *Heartbeat* (mobile gateways) ○. |
| Architectural constraints | - Federated peer-to-peer topology (no central directory) ✓. - One*MAPE-K* manager per gateway ✓. - Service register on a local *MongoDB 2.4* instance ✓. - Inter-gateway messaging through an *MQTT* broker ✓. - Resource-constrained edge nodes (Raspberry Pi 3 testbed) ✓.|
| Variation points| - Replication level (`20 %`, `60 %`, `100 %`) ✓. - Mobility environment (static, semi-mobile, fully-mobile) ✓. - Mobile-gateway speed (`10`-`50 km/h`) ✓. - Number of gateways (`500` in the Dublin simulation, `5` in the testbed) ✓. - Adaptation threshold `T = 0.15` ✓. - *DQN* hyperparameters (hidden nodes, learning rate) ✓.|
| Adaptation Scenarios| *E1* *Unforeseen* event ✓; *E2* *Scheduled* event ✓; *E3* *Periodic* event ✓|

### Architectural Reconstruction

The Target System of *IoT-SDP* is a federation of self-similar gateways, and each gateway hosts a `Service Register` and an `Autonomic Manager` running a local *MAPE-K* loop. Urban entities (citizens, authorities, places, events) reach the platform through *MQTT* topics exposed by each gateway's register interface; stationary gateways synchronise with peers via *Ping/Echo*, while mobile gateways broadcast *Heartbeat* messages as they move through the city (Figure 7.5). No central directory exists, so the federation's logically unified discovery surface is an emergent property of the sync tactics.

![IoT-SDP context diagram.](../../../img/07/cs2/cs_iotsdp_context.svg)

Figure 7.5. *IoT-SDP* context diagram.

Four actor groups drive the platform: city authorities (police, firefighters, mayor's office), citizens (residents, tourists), places (stations, museums, hotels, concert halls), and events (concerts, emergencies, accidents, maintenance). Any actor can issue a *City Request*, typically a discovery for a service such as `city navigation`, `metro line status`, or `ticket sale`; the request lands on the nearest gateway via *MQTT* and resolves either locally through the register or by forwarding to a peer (Figure 7.6). The same *MQTT* fabric carries both discovery requests and city events, so the register surface and the adaptation-trigger surface coincide.

![IoT-SDP use-case view.](../../../img/07/cs2/cs_iotsdp_use_case.svg)

Figure 7.6. *IoT-SDP* actor/use-case view.

A single *MAPE-K* loop per gateway splits across the two subsystems shown in Figure 7.7. On the Target System side sit the `Service Register` (a local *MongoDB 2.4* database), the `SR Internal Broker` (*SRIB*, the gateway's in-process publish-subscribe bus), the `Entity Request Handler` and `SR Notification Handler` for inbound *MQTT* traffic, and the `SR Database Manager` with its read and write pools. On the Controller side sits the `Autonomic Manager`, composed of `Planner`, `Manager`, `Rules`, `Goals`, and `Utility`; it observes the register through the `Controller Monitor Probe` on *SRIB* and actuates through the same bus. Inside the `Planner`, *E1* and *E2* take the rule-based branch and *E3* takes the *Deep-Q Network* branch.

![IoT-SDP controller and target-system composition.](../../../img/07/cs2/cs_iotsdp_components.svg)

Figure 7.7. *IoT-SDP* gateway composition: `Autonomic Manager` (Controller) and `Service Register` + *SRIB* + handlers + `SR Database Manager` (Target System).

Figure 7.8 shows the two extremes of the time-horizon spectrum in the authors' own notation. *E1* (Figure 7.8a) is an unforeseen city event (a natural disaster, protest, or accident) that arrives at a gateway with no prior warning; the `Planner` matches the event against a preprogrammed rule set and triggers a reactive register update. *E3* (Figure 7.8b) is a periodic event rooted in the city's entity behaviour (for example, citizens commuting on weekdays); the `Planner` runs a *Deep-Q Network* that observes the utility-function slope and learns to anticipate the pattern, updating the register before the event occurs. Neither scenario rewrites the gateway's workflow, but *E3*'s proactive path adds a steady-state load component that *E1* does not carry.

![(a) E1 unforeseen event.](../../../img/07/cs2/cs_iotsdp_event_e1.svg)
![(b) E3 periodic event.](../../../img/07/cs2/cs_iotsdp_event_e3.svg)

Figure 7.8. *IoT-SDP* focus scenarios: (a) *E1* unforeseen event (reactive rule-based) and (b) *E3* periodic event (proactive *DQN*).

Four items are out of scope here: the scheduled event *E2*; the full sequence and concurrency diagrams; the deployment and network views; and the complete tactic catalogue.

### Findings

Cabrera and Clarke's own results expose the central tension: the utility function collapses latency, network overhead, and resource utilisation into a single weighted scalar, and even with testbed numbers under target (`~25 %` CPU on Gateway 1, `~150 kB` adaptation overhead) every *Unforeseen* (*E1*) or *Scheduled* (*E2*) event drops utility below `T = 0.15` and triggers the reactive loop, while *E3*'s *DQN* underperforms regardless of hyperparameters. Under the *Performance vs Availability* lens we treat `rsrt` and `aspt` as *Availability* signals, so what Cabrera and Clarke present as a single-*QA* utility is actually two *QAs* sharing one weight vector. The two open questions [1] does not answer are whether the weight set encodes a deliberate *Performance*-versus-*Availability* trade-off or lets *Availability* free-ride on the *Performance* budget, and why the *DQN* underperforms when Figure 9 shows hyperparameters have negligible effect; the DASA evaluation picks both up.

## Cross-case Comparison

Both cases are commensurable because they share three things: both are *SAS* managed by a *MAPE-K* loop, both ship explicit adaptation scenarios with declared effectors, and both come with published *QA* claims from their original authors. They also share liveness-oriented tactics from the Bass 3rd-edition *Availability* catalogue: *TAS* uses service probes inside *ReSeP*, while *IoT-SDP* uses *Ping/Echo* between stationary gateways and *Heartbeat* from mobile gateways. The shared frameworks and tactics let the same analytical lens read both cases.

The cases diverge sharply on *MAPE-K* placement, adaptation style, technology stack, and *QA* vocabulary. *TAS* centralises one manager over a composite workflow and runs only reactive strategies (*Retry*, *Select Reliable*), and it is implemented on the Java-based *ReSeP* service platform running on conventional server hardware. *IoT-SDP* federates one manager per gateway, combines reactive rule-based adaptation for *E1* and *E2* with a proactive *Deep-Q Network* for *E3*, and is implemented in Python 3.5 with a local *MongoDB 2.4* register per gateway, deployed on resource-constrained Raspberry Pi 3 boards connected through an *MQTT* broker. On *QA* vocabulary, Weyns and Calinescu [1] name *Reliability*, *Performance*, *Cost*, and *Functionality* explicitly, while Cabrera and Clarke [1] collapse everything into a single *Performance* utility.

Under our *Performance vs Availability* lens we project both cases onto a shared *QA* plane: in *TAS* we re-read their *Reliability* as our *Availability* and keep their response-time target as our *Performance*; in *IoT-SDP* we re-read their `rsrt` and `aspt` as our *Availability* evidence (register freshness) while their latency, overhead, and resource utilisation stay as our *Performance*. *Cost* remains a first-class *QA* in *TAS* only.

The two cases are complementary rather than exhaustive. *TAS* names explicit numeric targets but stays reactive, while *IoT-SDP* adapts proactively but collapses its targets into a scalar utility; what one case leaves open the other fills. Together they cover reactive and proactive adaptation, and centralised and federated *MAPE-K* placement, which is enough to exercise *DASA* on two genuinely different architectures rather than two shades of the same one. What neither case reaches is safety-critical latency bounds, cloud-centric service discovery, or adaptation that requires workflow rewriting (*S4* and *S5* in *TAS*, topology change in *IoT-SDP*); those stay out of scope. The *DASA* evaluation of both cases is produced by the pipeline in this repo.

[^cs1-flags]: Flags in the *Description* column mark each fact as ✓ stated in the case-study documents or ○ inferred by us from those documents.
    
[^cs2-flags]: Flag convention as in the *TAS* specification summary. *Availability* is flagged as ○ because Cabrera and Clarke do not name it as a QA, but *Ping/Echo* and *Heartbeat* are *Availability* primitives in Bass 3rd ed., so we read register freshness as *Availability*.
