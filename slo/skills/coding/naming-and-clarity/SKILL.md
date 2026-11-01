---
name: naming-and-clarity
description: Self-describing domain names that distinguish predicates, guards, state changes, lifecycle operations and lock ownership. Clarity over cleverness.
when_to_use: Apply whenever naming or renaming a function, method, variable, parameter, DAO, error code, or docstring — always for domain, service, and persistence code, and for constructors, lifecycle helpers, and paired producer/consumer readers across a boundary. Load for every implementation and every review.
group: coding
kind: skill
source_prompt: naming-and-clarity.md
---

# Naming & Clarity

## Skill summary

- **Name:** `naming-and-clarity`
- **Description:** Self-describing domain names that distinguish predicates, guards, state changes, lifecycle operations and lock ownership. Clarity over cleverness.
- **When to use:** Every implementation and every review — especially domain, service, and persistence code, constructors, lifecycle helpers, and paired producer/consumer readers across a boundary.
- **Group:** `coding`
- **Kind:** `skill`
- **Source prompt:** `naming-and-clarity.md`

## Examples

The snippets in this skill are illustrative examples, not copied production code; they demonstrate naming distinctions without imposing a language or framework.

- The user asks you to name a new constructor, worker loop, or producer/consumer pair.
- You are reviewing a diff and a function name reads clever rather than descriptive.
- You need to decide between `build`, `create`, `start`, or `new` for a new helper.
- You are about to write `row = await session.get(...)`, `request: SomeDAO`, or `target = ...` in a domain service.
- A name you are about to write contains a noun (`voice_request`, `known_identity`, `requested_update`) that you cannot point to in the model.
- You are writing a docstring and reach for words like "evidence", "effects", or "projection".

## Guidance

**Clarity over cleverness is the overriding tie-breaker.** Whenever two names are in tension, pick the one a new reader understands without context. A clever name that saves a few characters costs every future reader a lookup.

A name has two sources of truth, and both must be honoured:

1. **The domain vocabulary** decides the *nouns*: entities, their fields, their states. (§0, §6)
2. **The operation actually performed** decides the *verb*. (§1, §2, §7)

A name that gets the verb right but invents the noun (`_lock_voice_request` — there is no "voice request") fails as badly as a clever verb.

---

## 0. Before naming anything: list the domain vocabulary

Do this once per task, before writing or reviewing code, and keep the list in your working notes:

1. **Entities** — the model/entity classes the task touches (e.g. `ContactObservation`, `Customer`).
2. **Fields and states** — their columns/attributes and enumerated states (e.g. `account_association`, `voice_completion_workflow_id`, `accepted`).
3. **Glossary** — terms used by the project's glossary, specification, README, or knowledge base for those entities (e.g. "contact statistics", "restriction").
4. **Operations** — what the domain says happens to them (e.g. "an interpretation is accepted", "a call is associated with a customer account").

**Every noun in a new identifier must come from this list.** If an honest name needs a noun that is not on it, you are inventing a concept. Stop and either (a) find the existing term, or (b) ask the user to name it. Never coin a term silently.

The project's own vocabulary always wins over this skill's examples. If the domain genuinely uses a word this skill discourages (for example, an interpreter whose spec defines an "evidence quote"), use it **for that concept only**.

---

## 1. Explicit, self-describing names

Name a function or identifier for **exactly what it does**. The name is the first and most-read piece of documentation. Ban opaque, cutesy, or "clever" verbs — they force the reader to open the body to learn what the name should have told them.

Real examples that were rejected and fixed:

| Rejected (too clever) | Fixed (self-describing) | Why |
|---|---|---|
| `pumpRelayDataFrames` | `readSessionRelayData` | "pump" hides that it reads one session's inbound relay-data frames and delivers them to that session |
| `runRelayDemux` | `routeRelayFrames` | "demux"/"run" hide that it reads every inbound frame and routes each to the right session |
| `wireOverlay` | `buildOverlay` | "wire" as a verb is jargon; the function builds the overlay |

Banned as verbs: **`demux`, `pump`, `wire`** (and anything in the same clever-jargon family). If you catch yourself reaching for a metaphor, use the plain verb for the actual operation instead.

Avoid **generic verbs that name no operation**: **`apply`, `handle`, `process`, `patch`, `perform`, `execute`, `manage`, `do`, `run`** (outside a CLI/task entry point). `associate`, `resolve`, `project`, and `effect` are banned unless the domain vocabulary (§0) uses that exact word for that exact operation.

`register`, `handle`, `reset` and `close` are valid on narrow interfaces that make the subject and operation clear, such as `connection.close()`. This does not justify vague helpers such as `handle_data()`. Preserve framework-required hooks and reserved attributes.

Rule of thumb: if a colleague cannot predict what the function does from its name alone, rename it.

---

## 2. State and lifecycle verb vocabulary

Choose verbs by effect, not storage medium. State may live in memory or on disk; use language-appropriate casing.

| Verb | Meaning | Example |
|---|---|---|
| `get` | Read existing state | `get_document_version()` |
| `create` | Establish new owned state | `create_cache_entry()` |
| `update` | Change existing state | `update_document_version()` |
| `delete` | Remove state | `delete_cache_entry()` |
| `save` | Persist an existing value | `save_document(document)` |
| `build` | Assemble a transient value without storing, registering, publishing or starting it | `build_cache_entry()` |
| `start` / `launch` | Begin background execution | `start_worker()` |

- `build` implies neither future persistence nor execution. Language-specific constructor spellings remain with the language owner, such as `skills/languages/go/go-conventions/SKILL.md`.
- Expose combined effects or split the operation: `get_or_create_cache_entry()` names lookup-or-creation; `ensure_cache_entry()` incorrectly suggests a guard. `build_and_create` means assemble then establish owned state, not necessarily persist it; neither stage starts background work.
- Do not add accessors, storage layers or unused helpers merely to fit the vocabulary.

### Predicates, guards and actions

- `is_<subject>_<condition>` returns a Boolean without changing state. An unmet condition returns false, not an error: `is_connection_open()`.
- `ensure_<subject>_<condition>` raises unless the condition already holds; it does not establish it: `ensure_connection_open()`.
- Actions name the change: `connection.close()`. `ensure_connection_closed()` requires an already-closed connection; it must not close it.
- A Boolean-returning action remains an action: `open_connection() -> bool` is not `is_connection_open()`.

### Versions

- `get_document_version()` reads; `update_document_version()` changes. Document whether the update increments or replaces the version and what becomes stale.
- `is_document_version(expected_version=3)` compares without mutation; `ensure_current_document_version(expected_version=3)` raises on mismatch without mutation.
- Keep independently versioned subjects distinct. Use `version` for a revision marker; preserve `generation` when it means content generation.

### Locks

- Attributes are nouns (`connection_lock`); operations use `acquire_connection_lock()` and `release_connection_lock()` when wrappers are needed. Native context-manager usage remains valid.
- `is_connection_lock_locked()` reports occupancy. `has_lock(...)` must establish ownership by the relevant caller; `.locked()` alone cannot do that.
- Do not name acquisition `update_lock()` or invent wrappers or ownership registries merely to support a name.

---

## 3. Producer/consumer pairs vs. same-direction readers

Use the **`publish…` / `consume…`** pair **only** for a genuine producer↔consumer relationship: one side *writes/produces* items onto a boundary (a channel, queue, or socket), the other side *reads/consumes* them. The matched vocabulary then makes the opposite roles obvious.

```go
// producer — writes jobs onto the queue
func (p *Dispatcher) publishJob(ctx context.Context, j Job) { ... }

// consumer — reads jobs off the queue
func (w *Worker) consumeJob(ctx context.Context) (Job, error) { ... }
```

**Do not force `publish`/`consume` onto two functions that do the same thing in the same direction.** Two concurrent readers that both *read* inbound frames are not a producer/consumer pair — name each for what it actually reads and at what scope:

```go
// caller: reads ONE session's inbound relay-data frames, delivers to that session's read channel
func readSessionRelayData(ctx context.Context, conn *Conn, sessionID uint64, readCh chan<- []byte) { ... }

// callee: reads ALL inbound frames on a registration, routes each to the right session (+ control frames)
func (d *Daemon) routeRelayFrames(ctx context.Context, regConn *Conn, relayAddr string) error { ... }
```

Naming these `publishRelayDataFrames` / `consumeRelayDataFrames` was a real mistake: both are inbound readers, so the publish/consume labels implied a producer/consumer split that does not exist and hid the true difference — one session vs. all sessions, data-only vs. all frame types. Name for the operation and its scope, not for a symmetry that isn't there.

---

## 4. Proportionate documentation comments

Explain **what happens, to which subject, why and when**, plus important arguments, results, side effects and errors. Identify callers when needed to understand the contract. Use the same domain vocabulary as the name; comments cannot excuse vague names or contradict the body.

A simple predicate needs no lengthy template. A stateful operation must identify its changes: “Advance the document version, invalidating pending saves” is clearer than “Update lifecycle state.”

Follow the language documentation owner for syntax: Python's `skills/languages/python/method-docstrings/SKILL.md`, Go's selected Godoc conventions, or TypeScript's selected JSDoc conventions.

---

## 5. Clarity over cleverness (the tie-breaker)

When any naming or documentation decision is genuinely a toss-up, choose the option that is clearest to a reader who has never seen the code. This principle overrides brevity, symmetry, and idiom. If a convention here ever conflicts with clarity in a specific case, clarity wins — and note the exception in a comment.

---

## 6. A variable holding an entity is named after the entity

The variable's name is the snake_case (Python, Go locals) or camelCase (TypeScript) form of the entity's type. Do not shorten it, generalise it, or describe how it was stored or fetched. This applies equally to parameters, attributes, loop variables, and test fixtures.

| Rejected | Fixed | Why |
|---|---|---|
| `row`, `record`, `obj`, `item`, `entity`, `data`, `instance` holding a `ContactObservation` | `contact_observation: ContactObservation` | Describes the storage, not the thing |
| `observation` holding a `ContactObservation` | `contact_observation` | Drops the qualifier; other kinds of observation become indistinguishable |
| `target` / `result` / `match` holding a tuple | Unpack into `customer`, `account_index`, `customer_account` | A role word hides which entities were found |
| `index` | `account_index` | Index *of what*? |
| `association` | `customer_account_association` | Association *of what with what*? |
| `request` holding an update DAO | `voice_contact_update: CustomerVoiceContactUpdateDAO` | "request" is transport vocabulary; name the payload's domain meaning |
| `previous` / `updated` | `previous_contact_statistics` / `updated_contact_statistics` | Say *what* changed, not only *when* |

Rules:

- **Two instances of the same type** get a domain qualifier, never a number: `incoming_customer_account` / `stored_customer_account`, not `account1` / `account2`.
- **ORM entity vs. its DAO** get distinguishable names when both are in scope: `contact_observation` / `contact_observation_dao`. Annotate each with its real type; never annotate an ORM `Customer` as `CustomerDAO`.
- **Collections** are the plural entity name, or `<entity>_by_<key>` for maps: `contact_observations`, `contact_observations_by_source_call_id`.
- **Optional lookups** keep the entity name; the type carries the optionality: `contact_observation: ContactObservation | None`.

```typescript
// TypeScript: the same rule in camelCase.
const contactObservation: ContactObservation = await findContactObservation(contactObservationId) // not: const row = ...
```

```go
// Go: short receiver names are idiomatic; entity locals still use the entity name.
contactObservation, err := store.GetContactObservation(ctx, contactObservationID) // not: row, err := ...
```

---

## 7. A method name is a domain verb on a domain noun

Shape: **`<verb>_<domain noun>[_<qualifier>]`**. The noun comes from §0; the verb names the actual operation (§2). The subject may instead be explicit in a narrow typed argument: `get_version(whose_version: DocumentVersionState)` is clear; `get_state(name: str) -> Any` is not. Use existing domain types, not new wrappers or registries solely to shorten names.

| Verb | Use for | Example |
|---|---|---|
| `get_` | Read one; absence is an error | `get_customer_account_for_voice_contact` |
| `find_` | Read one; absence is a valid `None` | `find_contact_observation` |
| `list_` | Read many | `list_account_voice_contact_observations` |
| `lock_` | Acquire a row or advisory lock on the entity | `lock_voice_contact_observation` |
| `create_` / `update_` / `delete_` | Establish, change or remove state in memory or on disk (§2) | `update_customer_contact_statistics` |
| `save_` | Persist an existing value | `save_document` |
| `replace_` | Remove and re-insert a well-defined subset | `replace_customer_contact_restrictions_for_call` |
| `mark_<state>` | Move the entity into a named domain state | `mark_voice_interpretation_workflow_completion` |
| `calculate_` | Derive a value without persisting | `calculate_customer_voice_contact_statistics` |
| `validate_` | Reject invalid input or state; returns nothing or raises | `validate_voice_contact_observation_account_association` |
| `build_` | Assemble a transient value without storing or starting it (§2) | `build_customer_account_association` |

Rules:

- **The name must survive a noun audit.** Split the name into words; every noun must be in the §0 list. `_lock_voice_request` fails ("voice request" is not an entity). `lock_voice_contact_observation` passes.
- **A method that only forwards to one branch is not a method.** `_apply_requested_update` that chooses between two calls belongs inline in the caller as an explicit `if`.
- **Two effects, two verbs, or a split.** If an honest name needs `and` (`update_contact_statistics_and_replace_restrictions`), either keep the `and` so the second side effect is visible, or split it into two methods. Never name it after one effect and hide the other.
- **Conditional methods state the condition in domain terms**, using fields from §0: `_save_contact_observation_if_customer_account_known`, not `_save_if_scope_complete`.
- **Error codes and exception classes follow the same rule.** `ErrorCustomerAccountNotFound("customer_account_not_found")`, not `ValueError("unpersisted_voice_evidence")`.

Rejected → fixed, from a real review (illustrative, not copied production code):

| Rejected | Fixed | What was wrong |
|---|---|---|
| `_lock_voice_request` | `lock_voice_contact_observation` | No such thing as a "voice request"; it locks a voice `ContactObservation` |
| `replace_voice_evidence` | `update_customer_contact_statistics` | "evidence" is not a domain term; it updates contact statistics |
| `_apply_requested_update` | inline the branch into `invoke()` | "requested update" is no entity; "apply" is no operation |
| `_associate_known_identity` | `_save_contact_observation_to_customer_account` | "known identity" is no entity; it saves a `ContactObservation` against a customer account |
| `_load_voice_evidence` | `list_account_voice_contact_observations` | "load" + invented noun; it lists the account's voice contact observations |
| `_patch_voice_observed_evidence` | `update_customer_contact_statistics` | "patch" is no operation; "observed evidence" is no entity |
| `_voice_effect_result` | `build_customer_voice_contact_update_result` | "effect" is no domain term; it builds a result DAO |
| `mark_voice_completion(row=...)` | `mark_voice_interpretation_workflow_completion(contact_observation=...)` | Completion *of what*; `row` names storage |

---

## 8. Never leak working vocabulary into domain code

Your own process has a vocabulary: verification, review, orchestration, specifications, transport. Those words describe *your work*, not the *domain*, and they must not appear in identifiers, DAO names, error codes, log messages, or docstrings unless §0 lists them for that concept.

Banned unless the domain vocabulary contains them: **`evidence`, `effect`, `material effect`, `source effects`, `projection`, `phase`, `contract`, `target`, `request`, `payload`, `context`, `uncertainty`, `artifact`, `handoff`, `scope`, `identity` (as a stand-in for a specific entity)**.

How it leaks, and the fix:

- A verification step "records evidence" → the code gets `voice_evidence`. Name the entity: `contact_observation`.
- A spec talks about "effects" of an update → the DAO becomes `...EffectResultDAO`. Name what changed: `CustomerVoiceContactUpdateResultDAO`.
- An HTTP or queue layer uses "request" → a domain service parameter becomes `request`. Name the domain payload: `voice_contact_update`.

---

## 9. Existing names are history, not precedent

"Stay consistent with existing naming" covers **style**: casing, prefixes, `get_` vs. `find_` conventions, file layout. It does **not** cover **vocabulary**.

- If the file you are editing uses `row` 100 times, new and changed code still uses `contact_observation`. Do not rename untouched code as a side quest; do not copy the bad name forward either.
- If a **persisted column or external contract** carries a non-domain name (e.g. a JSON key `observed_evidence`), keep that exact name **at the boundary only** (model column, serialised key, API field), use the domain name everywhere else, and **report the mismatch** to the user as a candidate migration. Never derive new method or DAO names from it (`_patch_voice_observed_evidence` is what happens when you do).
- If the user or a review rejected a name, the replacement must pass §0 and §7 too. Renaming `known_identity` to `customer_scope` swaps one invented noun for another.
- Before renaming, inspect bodies and callers; distinguish checks from initialization. Update callers, interfaces, dynamic routing, tests and examples together. Preserve ordering, post-await validation, cleanup and error policies; a clearer name is not a behavior change.

---

## 10. Worked example

Illustrative, not copied production code. The method reads correctly only when every name passes §0–§9.

**Rejected:**

```python
async def replace_voice_evidence(*, request: CustomerVoiceUpdateDAO, db_session: AsyncSession) -> CustomerVoiceUpdateResultDAO:
    """Replace current source effects while retaining caller transaction ownership."""
    observation = await CustomerService._lock_voice_request(request=request, db_session=db_session)
    target = await CustomerService._find_account_for_call(request=request, observation=observation, db_session=db_session)
    customer, index, account = target
    evidence = await CustomerService._load_voice_evidence(association=association, db_session=db_session)
    previous = account.calls.observed_evidence
    updated = CustomerService._build_observed_voice(request=request, previous=previous, evidence=evidence)
```

Problems: invented nouns (`voice_request`, `voice_evidence`, `source effects`), storage/role names (`observation`, `target`, `index`, `account`, `request`), generic verbs (`replace`, `load`, `patch`), and no local types.

**Fixed:**

```python
async def update_customer_contact_statistics(
    *,
    voice_contact_update: CustomerVoiceContactUpdateDAO,
    db_session: AsyncSession,
    autocommit: bool = True,
) -> CustomerVoiceContactStatsDAO:
    """Recalculate a customer account's voice contact statistics after an accepted call.

    Called by UpdateCustomerStateAppService once a voice interpretation is accepted.
    Locks the call's ContactObservation, associates it with the existing customer account,
    and recalculates statistics from the account's accepted voice contact observations.
    Commits unless ``autocommit=False``.
    """
    contact_observation: ContactObservation = await ContactObservationService.lock_voice_contact_observation(
        contact_observation_id=voice_contact_update.contact_observation_id, db_session=db_session
    )
    customer: Customer
    account_index: int
    customer_account: CustomerAccountDAO
    customer, account_index, customer_account = await CustomerService.get_customer_account_for_voice_contact(
        contact_observation=contact_observation, db_session=db_session
    )
    contact_observations: list[ContactObservation] = (
        await ContactObservationService.list_account_voice_contact_observations(
            customer_account=customer_account, db_session=db_session
        )
    )
    updated_contact_statistics: CustomerVoiceContactStatsDAO = (
        CustomerService.calculate_customer_voice_contact_statistics(contact_observations=contact_observations)
    )
```

Every noun is an entity or glossary term, every verb is from §2/§7, every local is entity-named and typed, and the docstring says WHAT, WHO, and WHEN in domain words.

---

## Quick checklist

- [ ] Did you list the domain vocabulary (entities, fields, states, glossary) before naming? (§0)
- [ ] Every noun in every new name is on that list — none invented? (§0, §7)
- [ ] Can a reader predict what the function does from its name alone?
- [ ] Plain verbs for real operations; lifecycle names scoped to clear interfaces and framework-required names preserved?
- [ ] `is_` predicates are pure, `ensure_` guards require existing conditions, and actions name changes?
- [ ] `get/create/update/delete` describe state operations regardless of storage; `save` means persistence?
- [ ] `build` only assembles a transient value; combined names expose both effects?
- [ ] Subject explicit in the name or a narrow type; version reads, updates and checks distinct?
- [ ] Lock attributes are nouns; acquire/release are actions; occupancy is not claimed as ownership?
- [ ] `start…` / `launch…` left as-is for background-task/loop spawning (not folded into `build`)?
- [ ] Does any language-specific constructor spelling follow the applicable language owner rather than this generic skill?
- [ ] Producer/consumer pair across a boundary named `publish…` / `consume…` with a shared noun?
- [ ] Every variable holding an entity is named after its type (`contact_observation`, never `row` / `observation` / `target` / `request`) and annotated with its real type? (§6)
- [ ] Every side effect visible in the method name — no second effect hidden behind the first? (§7)
- [ ] No working vocabulary (`evidence`, `effect`, `projection`, `scope`, `request`) in names, error codes, or docstrings? (§8)
- [ ] No bad existing name copied forward for "consistency"; non-domain persisted names kept at the boundary only and reported? (§9)
- [ ] Comments proportionately explain the subject, operation, reason, timing, side effects and errors?
- [ ] Renames propagated through references and dynamic routing without changing behavior?
- [ ] When in doubt, did clarity win over cleverness?
