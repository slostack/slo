# R161-4 public API audit — author closure168

Scope: all locally declared public classes/functions/methods/properties and constructors in `src/agents/slo_agent/herdr/*.py`, `sessions/identity.py`, `sessions/token_format.py`, `orchestrator/context_reader.py`. Full bodies of these ten files were read, including private delegates used by the public boundaries. AST inventory cross-check prevents omission; inherited Pydantic APIs are library contracts, not locally authored methods. Private validators/helpers and private `_WindowsByteLock` are not new public APIs. Package `__init__.py` is inert. This is a finite documentation audit, not independent full-feature review.

Notation: A=Args documented; R=Returns documented; E=Raises documented; N=not applicable; S=unambiguous summary suffices (simple predicate/no-op per method-docstrings exception). For synchronous APIs cancellation is N: caller offloading/join ownership is stated where needed. Constructors return None and acquire nothing unless stated. Protocol rows document required behavior, not executable implementations. Valid typed inputs are the precondition; arbitrary programmer misuse is not promised fixed-error translation.

## Data boundaries (dao.py)

Each row's construction inputs are its annotated `Field(description=...)` declarations; return is the named frozen value; validation errors use the declared Pydantic boundary. These values own no task, descriptor or cleanup. Private carriers have repr-hidden fields, not permission to publish `model_dump`. `HerdrReportSnapshotDAO` and `HerdrLifecycleAcknowledgementDAO` inherit session reporting validation rather than HerdrDAO's wrapper.

| Public type | Contract / ownership audit |
|---|---|
| HerdrDAO | Frozen, extra-forbid, private validation-input suppression |
| HerdrDisplayTokenDAO | Bounded complete generated token; no truncation |
| HerdrReportSnapshotDAO | Public session state plus unique ordered tokens |
| HerdrRestorePoolEntryDAO | Exact configured scalar policy, not live routing |
| HerdrRestorePoolDAO | Immutable ordered entries, minimum two |
| HerdrRestoreConfigDAO | Allowed exact private policy and resolved paths |
| HerdrRestoreCaptureDAO | Memory-only config, no reference |
| HerdrPublicationDAO | Atomic generation/facts/capture, matching identity |
| HerdrRestoreReferenceDAO | Canonical opaque revision |
| HerdrRestoreRecordDAO | Private schema1/config envelope, no history |
| HerdrSavedRestoreDAO | Reference bound to exact capture/generation |
| HerdrRemoteBindingDAO | Possible/confirmed admitted effect, distinct from ack |
| HerdrCommandOutcomeDAO | Fixed status/numeric exit, no raw output |
| HerdrCommandResultDAO | Bounded private successful JSON; strict spawn-failure relationship |
| HerdrReporterCloseOutcomeDAO | Intermediate remote evidence versus final disposal; retained implies uncertain |
| HerdrReportTicketDAO | Exact single-operation authority, publication/close shape |
| HerdrLifecycleAcknowledgementDAO | Semantic state independent of display revision |
| HerdrVisualizerRequestDAO | Parent and captured root; eligibility still session-owned |
| VisualizerLaunchOutcomeDAO | Submission/manual recovery, not paint proof |
| HerdrVisualizerAttemptDAO | One-shot operation set; pane iff known |
| HerdrReporterConfigDAO | Captured absolute paths and fixed deadlines; no constructor I/O |
| HerdrSequenceStateDAO | Independent durable counters; wire upper bound enforced by store |
| HerdrCliCommandDAO | Private allowed semantic argv, not executable choice |

Literal aliases `HerdrDestination`, `HerdrDisplayKey`, `HerdrCommandStatus`, `HerdrReportOperation`, `HerdrViewerOperation` enumerate their complete finite vocabulary. `RESTORE_UNAVAILABLE_MESSAGE` is fixed safe copy. Reporter `HERDR_TOKEN_KEYS` derives the display inventory. No lifetime or Args/Returns/Raises applies to constants/aliases. `HerdrOutputLimitError` is an empty private-pipe signal with a class docstring; no custom constructor contract.

## Protocol APIs (dao.py)

| API | A/R/E | Ownership, cancellation and cleanup |
|---|---|---|
| HerdrRestoreUnavailableError.__init__ | A/N/N | Ignores arbitrary message, fixed diagnostic |
| HerdrRestoreStoreProtocol.save | A/R/E | Off-loop immutable durable save; cleanup failure refuses |
| HerdrRestoreResourceOwner.retains_external_resources | N/S/N | Read after save joins; unresolved owner remains reachable |
| HerdrRestoreResourceOwner.close | N/N/E | Off-loop after saves; overlap/cleanup refusal retains owner |
| HerdrCommandAdmission.try_admit | N/R/N | Synchronous under lock; no await before spawn registration |
| HerdrCommandAdmission.complete | A/N/N | Once before unlock, including stale/cancelled effects |
| HerdrReporterProtocol.start | N/N/E | Inert construction; join activation on cancellation, session final cleanup |
| HerdrReporterProtocol.publish | A/N/E | Synchronous frozen handoff; real rollback/conflict refusal, null discard |
| HerdrReporterProtocol.close | N/R/E | Join withdrawal; default drained NOT disposal permission |
| HerdrReporterProtocol.close_transport | N/R/E | Final resource evidence; cancellation after join |
| HerdrReporterProtocol.drain_retained_external_resources | N/R/E | Local-only joined cleanup, no remote retry |
| HerdrReporterProtocol.build_visualizer | N/R/E | Inert shared-transport viewer; null/unavailable refusal |
| HerdrReporterProtocol.revoke_viewer_admission | N/N/N | Synchronous cutoff before cleanup |
| HerdrReporterProtocol.record_publication_failure | N/N/N | Fixed diagnostics only |
| HerdrReporterProtocol.allows_viewer_admission | N/S/N | Live authority, never snapshot permission |
| HerdrReporterProtocol.destination | N/S/N | Current closed routing vocabulary |
| HerdrReporterProtocol.retains_external_resources | N/S/N | Local ownership, not remote certainty |

## Reporter APIs (reporter.py)

| API | A/R/E | Ownership, cancellation and cleanup |
|---|---|---|
| HerdrReporter.__init__ | A/N/N | Inert session-owned collaborators; optional restore resource capability |
| HerdrReporter.build | A/R/N | Disabled before stores; unavailable not fallback; caller starts/closes |
| HerdrReporter.start | N/N/E | One cached activation; worker only after release; cancellation joins, session owns final close |
| HerdrReporter.publish | A/N/E | No I/O/task; one pending pointer; rejects generation conflicts before mutation |
| HerdrReporter.revoke_viewer_admission | N/N/N | Synchronous ordinary AND viewer cutoff, clears pending |
| HerdrReporter.allows_viewer_admission | N/S/N | Current lease/counter/activation/transport authority |
| HerdrReporter.destination | N/S/N | Herdr only while authority exists, otherwise unavailable |
| HerdrReporter.close | N/R/E | Cached remote/sticky evidence; normal lease retained until transport drains |
| HerdrReporter.retains_external_resources | N/S/N | Pane, transport and optional restore ownership independent of remote certainty; revision170 reads sequence-owner truth even after failed acquisition, not successful admission |
| HerdrReporter.close_transport | N/R/E | After viewer/reporter close; joined final lease/process evidence, sticky uncertainty |
| HerdrReporter.drain_retained_external_resources | N/R/E | One cached final local attempt; ambiguous FD never reclosed; retain unresolved owner |
| HerdrReporter.build_visualizer | N/R/E | Session retains/closes viewer before reporter; live authority required |
| HerdrReporter.record_publication_failure | N/N/N | Fixed rate-limited publication diagnostic |
| HerdrReporterAdmission.__init__ | A/N/N | One exact ticket, no ownership transfer |
| HerdrReporterAdmission.try_admit | N/R/N | Single synchronous attempt under shared lock |
| HerdrReporterAdmission.complete | A/N/N | Once, stale result cannot acknowledge newer facts |

## Storage APIs

| API | A/R/E | Ownership, cancellation and cleanup |
|---|---|---|
| HerdrRestoreStore.__init__ | A/N/N | Inert path owner; operations off-loop |
| HerdrRestoreStore.retains_external_resources | N/S/N | Existing unresolved operation lease |
| HerdrRestoreStore.close | N/N/E | Serialize after join; inspection-only ambiguity, fixed refusal |
| HerdrRestoreStore.save | A/R/E | Immutable durable reference only after cleanup; orphan not adopted; no history/GC |
| HerdrRestoreStore.load | A/R/E | Read-only exact revision, existing lock only; fixed refusal, independent policy |
| HerdrSequenceUnavailableError.__init__ | N/N/N | Fixed diagnostic, no resource |
| HerdrFileLease.__init__ | N/N/N | Inert descriptor owner |
| HerdrFileLease.validate | A/R/E | Read-only lstat evidence, not open-handle proof; unsafe refusal or OSError |
| HerdrFileLease.acquire | A/N/E | Nonblocking exclusive FD; serialized caller; rollback close failure retains owner |
| HerdrFileLease.require_held | A/N/E | Substitution refusal preserves original handle; inspection may fail |
| HerdrFileLease.retains_external_resources | N/S/N | No inspection or action |
| HerdrFileLease.close | N/N/E | Never retry ambiguous raw FD; EBADF/different inode absence under exclusive-owner assumptions; same inode not generation proof |
| HerdrSequenceStore.__init__ | A/N/N | Inert hashed pane namespace, not session identity |
| HerdrSequenceStore.acquire | N/N/E | Lifetime lease, secure directories; corrupt bytes never repaired |
| HerdrSequenceStore.retains_external_resources (170) | N/S/N | Pure unresolved lease ownership after acquisition/cleanup joins, including failed rollback; no I/O or reservation/admission permission |
| HerdrSequenceStore.reserve | A/R/E | Complete bounded reread, durable signed64 reservation; failure disables, legal gaps only |
| HerdrSequenceStore.close | N/N/E | After reservations/transport join; persistent files retained; ambiguous FD policy delegated |

## Support/transport APIs (service.py)

| API | A/R/E | Ownership, cancellation and cleanup |
|---|---|---|
| NullHerdrReporter.__init__ | A/N/N | Captured destination only, zero resources |
| NullHerdrReporter.start | N/N/N | No work or cancellation point |
| NullHerdrReporter.publish | A/N/N | Discard without validation/reference retention |
| NullHerdrReporter.close | N/S/N | Safe no-resource evidence, no awaits |
| NullHerdrReporter.close_transport | N/S/N | Independent no-resource proof, does not retry intermediate close |
| NullHerdrReporter.drain_retained_external_resources | N/S/N | Independent inert final drain, no awaits |
| NullHerdrReporter.retains_external_resources | N/S/N | Always false |
| NullHerdrReporter.allows_viewer_admission | N/S/N | Always false |
| NullHerdrReporter.revoke_viewer_admission | N/N/N | No permission to revoke |
| NullHerdrReporter.record_publication_failure | N/N/N | No diagnostics |
| NullHerdrReporter.build_visualizer | N/N/E | Always fixed unavailable, NoReturn |
| HerdrEnvironmentGate.build | A/R/N | No filesystem/resource probes; invalid config unavailable, bad profile compact; fixed diagnostics |
| HerdrSnapshotProjector.build | A/R/E | Existing usage only; pure fixed/numeric values; identity/state validation |
| HerdrTaskJoin.wait | A/R/N | Shields retained task, consumes caller cancellation and returns flag; retrieves task exceptions; no timeout/ownership transfer |
| HerdrTransportAdmission.__init__ | A/N/N | One invocation-local synchronous delegate |
| HerdrTransportAdmission.try_admit | N/R/E | Attempt consumed before delegation; delegate failure escapes to transport normalization |
| HerdrTransportAdmission.complete | A/N/E | Completion consumed before delegate, no retry on callback defect |
| HerdrCliTransport.__init__ | A/N/N | Inert shared lock/process owner, fixed environment allowlist |
| HerdrCliTransport.closed | N/S/N | Monotonic admission seal |
| HerdrCliTransport.resources_drained | N/S/N | Local handle absence only |
| HerdrCliTransport.close | N/R/E | Seal, cached joined cleanup; no remote release; cancellation after join |
| HerdrCliTransport.drain_retained_resources | N/R/E | One local retry, no callback/command repeat; retain unresolved handles |
| HerdrCliTransport.invoke | A/R/E | Deadline includes lock, not OS reap; waiter cannot drain holder; admitted cleanup/accounting before unlock; cancellation propagates after join |
| service.__getattr__ | A/R/E | Lazy compatibility classes only; unsupported name AttributeError; expanded168 |

Simple null result/predicate summaries already specify the whole return contract; adding repetitive sections would add no ambiguity resolution. No explicit cancellation promise applies to null async methods because their bodies do not suspend. Protocol real-owner cancellation remains distinct.

## Viewer and extracted APIs

| API | A/R/E | Ownership, cancellation and cleanup |
|---|---|---|
| HerdrVisualizerLauncher.__init__ | A/N/N | Inert ledger; borrowed transport; nonthrowing live authority |
| HerdrVisualizerLauncher.close | N/N/E | Session-owned shared launches cancelled/joined; no pane or transport close |
| HerdrVisualizerLauncher.invoke | A/R/E | Session validates eligibility; same-parent shared task shielded from waiter cancellation; one-shot attempt persists; no liveness claim |
| HerdrViewerAdmission.__init__ | A/N/N | Exact attempt identity and operation captured before wait |
| HerdrViewerAdmission.try_admit | N/R/N | Consume once under lock against live authority |
| HerdrViewerAdmission.complete | A/N/N | No outcome grants another split/run |
| validate_session_id | A/R/E | Pure ordinary UUID(any version)/slug normalization; path guards |
| is_canonical_uuid_session_id | A/R/N | Pure exact spelling predicate, no ordinary-resume tightening |
| CompactTokenFormatter.format | A/R/N | Pure exact half-up; nonnegative caller precondition, no validation/clamp |
| OrchestratorContextReader.load | A/R/N | Existing layout/schema, caller offloads; OS/validation failure becomes None, no logging or writes |

## Result and limits

R161-4 author documentation closure: existing165/166 expansion agrees with actual bodies; only compatibility `service.__getattr__` needed an applicable Args/Returns/Raises addition. No behavior changes. Focused docs-boundary gate35 passes. Specific instance ownership and no-await atomic admission remain intact.164 ambiguous-FD/restore retention,165 intermediate/final distinction and167 independent null final cleanup are preserved. Seven166 updated activation expectations are not reverted to retained-intermediate assertions; all eight prior failures are included in the fresh full gate.

Required fresh gates and manifest are in `final-core-gates-168.md`. Independent core rereview, wiring/harness/static review, full-review synthesis and separate fresh Completion remain required. Live USER-DEFERRED; compatibility UNVERIFIED.
