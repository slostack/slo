---
name: coding-rules
description: Broad software design rules for reducing complexity and improving code clarity.
when_to_use: Apply when designing, implementing, reviewing, or refactoring code across languages and frameworks.
group: coding
kind: skill
---

## Applicability and precedence

These broad rules are defaults. Applicable language, framework, feature, and project-specific requirements override them on the relevant point; generic obligations remain intact. Unresolved specific-to-specific conflicts require a user decision. Language examples illustrate principles and do not impose universal syntax.

# Software Design Instructions for Coding Agents

*Source: John Ousterhout, "A Philosophy of Software Design" (2018).*

## Goal

Minimize system complexity. Working code is the baseline, not the finish line.
Every module, interface, name and comment must reduce the effort a future
reader needs to understand and change the code.

Complexity is anything that makes code hard to understand or modify. It shows
up as change amplification (one change touches many files), cognitive load
(too much context needed) and unknown unknowns (unclear what must change). It
comes from dependencies and obscurity. It accumulates in small steps, so
accept no "small" mess.

## Instructions

1. **Work strategically.** Spend roughly 10–20% of effort on design: refining
   abstractions, weighing alternatives, clean interfaces, documented
   invariants. Fix design flaws when found; do not patch around them. Revisit
   abstractions as requirements change.

   *Examples:*
   - Python: `if user.can(Permission.DELETE_POST):  # one rule, not is_admin or is_owner copied everywhere`
   - Go: `allowed := user.Can(PermDeletePost) // one rule, not repeated role checks`
   - TypeScript: `const allowed = user.can("deletePost"); // one rule, not repeated role checks`

2. **Write the comments first.** For a new class: write the class comment,
   then the signatures and comments of key public methods, then refine them
   until the abstraction is clear, then declare fields with invariant
   comments, then implement. If something is hard to describe simply,
   redesign it before implementing.

   *Examples:*
   - Python: `def get_page(url: str) -> Page: """Return the cached page for url, fetching it at most once per TTL."""`
   - Go: `// GetPage returns the cached page for url, fetching it at most once per TTL.`
   - TypeScript: `/** Returns the cached page for url, fetching it at most once per TTL. */`

3. **Make modules deep.** Offer a lot of functionality behind a small, simple
   interface. Make the common case trivial and still allow advanced use.
   Reject shallow modules whose interface is as complex as their
   implementation.

   *Examples:*
   - Python: `text = Path("notes.txt").read_text()  # encoding, buffering and closing are hidden`
   - Go: `data, err := os.ReadFile("notes.txt") // open, size, read loop and close are hidden`
   - TypeScript: `const text = await fs.readFile("notes.txt", "utf8"); // all I/O details are hidden`

4. **Make modules somewhat general-purpose.** Implement today's needs behind an
   interface that serves several use cases. Keep caller-specific UI or policy
   out of core engines. Ask: what is the simplest interface that covers
   current needs, where else could it be reused, and does using it require
   awkward wrapper code?

   *Examples:*
   - Python: `buffer.delete(start=cursor - 1, end=cursor)  # not buffer.handle_backspace()`
   - Go: `buf.Delete(Range{Start: cursor - 1, End: cursor}) // not buf.Backspace()`
   - TypeScript: `buffer.delete({ start: cursor - 1, end: cursor }); // not buffer.onBackspace()`

5. **Hide information.** Keep each design decision (data structure, format,
   protocol, concurrency model, parsing) inside one module.
   - Do not let the same knowledge appear in several classes.
   - Do not expose internal structures through accessors or mechanical
     getters and setters.
   - Group code by shared knowledge, not by execution order (no
     `FileReader` → `FileParser` split).
   - Do the right thing by default; do not make callers request common
     behavior.

   *Examples:*
   - Python: `config = ConfigStore.load(path)  # only ConfigStore knows the file is JSON`
   - Go: `cfg, err := config.Load(path) // only package config knows the file format`
   - TypeScript: `const config = ConfigStore.load(path); // callers never see the JSON shape`

6. **Give each layer a different abstraction.** Remove pass-through methods
   that only forward to a near-identical signature. Avoid shallow decorators
   and wrappers. Do not thread parameters through methods that don't use
   them; use a context object or inject at construction.

   *Examples:*
   - Python: `orders.save(order)  # call the repository; delete an OrderService.save that only forwarded`
   - Go: `err := orders.Save(ctx, order) // delete a Service.Save that only forwarded`
   - TypeScript: `await orders.save(order); // delete a service method that only forwarded`

7. **Pull complexity down.** When complexity is unavoidable, absorb it in the
   implementation rather than pushing it to callers. Do not add configuration
   parameters to dodge a decision; compute sensible values instead.

   *Examples:*
   - Python: `response = client.get(url)  # client owns timeouts and retries; no retry_count=3 at each call`
   - Go: `resp, err := client.Get(ctx, url) // client owns retries and backoff`
   - TypeScript: `const response = await client.get(url); // no { retries: 3, backoff: 500 } at each call`

8. **Decide what belongs together.**
   - Combine code that shares knowledge or formats, that simplifies the
     caller's interface when merged, or that duplicates logic.
   - Separate general mechanisms from special-purpose policy, and separate
     code that shares no state or concepts.
   - Split a method only when each part is a clean, independent abstraction.
     Never create methods that can't be understood without reading another.

   *Examples:*
   - Python: `header = Header.from_stream(stream)  # replaces read_header() followed by parse_header()`
   - Go: `hdr, err := ReadHeader(r) // one function owns the header layout`
   - TypeScript: `const header = Header.fromStream(stream); // not readHeader() then parseHeader()`

9. **Define errors out of existence.** In order of preference:
   1. Change semantics so edge cases have a valid result (deleting a missing
      item is a no-op; out-of-range slices clamp).
   2. Mask the error at a low level (e.g. retry) so callers never see it.
   3. Aggregate: handle a general error category once at a top-level
      boundary, with rich context.
   4. Crash with diagnostics on unrecoverable bugs or invariant violations.

   Merge special cases into the normal code path.

   *Examples:*
   - Python: `cache.pop(key, None)  # removing a missing key is a no-op, not a KeyError`
   - Go: `delete(cache, key) // no error when key is absent`
   - TypeScript: `cache.delete(key); // returns false for a missing key, never throws`

10. **Comment what the code cannot say.**
    - Never restate the code.
    - Low level: state ranges (inclusive/exclusive), units, null meaning and
      invariants.
    - High level: state intent and strategy for classes, interfaces and
      complex algorithms.
    - Interface comments: preconditions, side effects, errors, return
      contract. No implementation details.
    - Implementation comments: what and why, not how.
    - Document cross-module decisions once, in a central place, and
      reference it.

    *Examples:*
    - Python: `end: int  # exclusive byte offset, not a character index`
    - Go: `TimeoutMs int // zero means no timeout; negative values are invalid`
    - TypeScript: `width: number; // CSS pixels, including padding`

11. **Choose precise names.** Avoid vague names (`data`, `status`, `result`)
    outside tiny scopes. Name booleans as predicates (`cursorVisible`). Use
    each term for exactly one concept everywhere. The farther a name is used
    from its declaration, the more descriptive it must be.

    *Examples:*
    - Python: `pending_request_count = len(queue)  # not n`
    - Go: `cursorVisible := true // not blinkStatus`
    - TypeScript: `const isRetryAllowed = attempt < maxAttempts; // not flag`

12. **Make code obvious.** Optimize for reading, not writing.
    - Use whitespace to separate logical blocks.
    - Use named domain types instead of generic containers like `Pair<T, U>`.
    - Match declared and allocated types where possible.
    - Do not surprise readers (e.g. no hidden thread start in a constructor).

    *Examples:*
    - Python: `return Leg(meters=12.0, seconds=3.1)  # not return (12.0, 3.1)`
    - Go: `type Leg struct{ Meters, Seconds float64 } // not [2]float64`
    - TypeScript: `type Leg = { meters: number; seconds: number }; // not [number, number]`

13. **Stay consistent.** Do similar things the same way and different things
    differently. Follow existing naming, formatting, interface and pattern
    conventions, even if you prefer another style. Do not change a convention
    without a project-wide reason and a full migration.

    *Examples:*
    - Python: `def find_invoice(invoice_id: str) -> Invoice | None:  # matches the existing find_* lookups`
    - Go: `func (s *Store) FindInvoice(id string) (Invoice, error) // matches the existing Find* methods`
    - TypeScript: `findInvoice(id: string): Promise<Invoice | undefined>; // matches the existing find* methods`

14. **Apply common practices with care.**
    - Prefer interface inheritance over deep implementation inheritance; keep
      parent fields private.
    - Make each increment an abstraction, not a raw feature.
    - With TDD, design the abstraction first; do not let micro-iterations
      produce shallow, tactical code.

    *Examples:*
    - Python: `def archive(store: Store) -> None:  # Store is a Protocol, not a base class to subclass`
    - Go: `type Store interface{ Get(key string) ([]byte, error) } // compose behind an interface, no inheritance`
    - TypeScript: `class DiskStore implements Store { /* ... */ } // implement an interface, don't extend a base class`

15. **Design for performance.** Measure before optimizing. Find the minimal
    code for the common path, remove special cases, wrappers and redundant
    checks from it, and handle rare cases off the fast path.

    *Examples:*
    - Python: `if not text.isascii(): text = normalize("NFC", text)  # only rare inputs pay for normalization`
    - Go: `if !isASCII(s) { s = norm.NFC.String(s) } // only rare inputs pay for normalization`
    - TypeScript: `if (!/^[\x00-\x7F]*$/.test(s)) s = s.normalize("NFC"); // only rare inputs pay for normalization`

16. **Modify code as if designing it fresh.** After a change, the code should
    look as if it had been designed with that change in mind. Keep comments
    next to the code they describe, record rationale in comments rather than
    only in commit messages, do not duplicate comments, and review the diff
    to confirm comments are still accurate.

    *Examples:*
    - Python: `price = Price(amount=Decimal("9.99"), currency="EUR")  # currency lives on Price, not as a new parameter everywhere`
    - Go: `p := Price{Amount: 999, Currency: "EUR"} // currency lives on Price, not as a new parameter everywhere`
    - TypeScript: `const price: Price = { amount: 999, currency: "EUR" }; // not total(amount, currency, ...)`

## Skill summary

Use these principles to reduce complexity while designing, implementing, reviewing, or refactoring software. Treat them as broad defaults: the applicable language, framework, feature, and project-specific guidance takes precedence on the points it explicitly governs.

## Examples

- Before adding a wrapper or parameter, identify the decision it would hide and ask whether the owning layer can provide a smaller interface instead.
- Before publishing a runtime, resource, or externally visible state, validate its invariants and make cleanup ownership explicit.
- During review, prefer precise names, consumer-owned interfaces, bounded diagnostics, and tests that prove lifecycle and failure behavior rather than only the happy path.

## Guidance

Start by clarifying the abstraction and its ownership, then implement the smallest coherent interface. Keep shared knowledge in one place, make edge cases explicit, and test each decision boundary. When a specific project or language rule conflicts with this generic guidance, follow the specific rule and record any unresolved conflict instead of silently inventing a second convention.
