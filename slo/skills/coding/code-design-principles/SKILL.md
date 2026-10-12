---
name: code-design-principles
description: Language-independent guidance for ownership, deep modules, and declarative code structure.
when_to_use: Apply when designing, implementing, reviewing, or refactoring code in any language or framework.
group: coding
kind: skill
---

## Guidance

## Applicability and precedence

This skill is generic across languages and frameworks. Apply it when shaping module boundaries, deciding which object owns behavior, or making control flow easier to read. Language, framework, feature, project, and user requirements take precedence where they are more specific; this skill remains applicable everywhere else. When two equally specific rules conflict, stop and resolve the conflict rather than inventing a silent exception.

This skill complements, rather than replaces, [`skills/coding/coding-rules/SKILL.md`](../coding-rules/SKILL.md). Use `coding-rules` for the broader design principles, and use this skill for the narrower questions of ownership, module depth, and declarative structure. Do not copy or restate all sixteen principles from that skill.

## Skill summary

- Give each decision and resource a clear owner.
- Put substantial capability behind small, stable interfaces.
- Make orchestration read like a sequence of named decisions and actions.
- Prefer delegation, early exits, and explicit boundaries over state inspection and nested branching.

## Ownership: put behavior with the knowledge

- Assign each policy, invariant, protocol detail, persistence format, and resource lifecycle to one owner.
- Let callers request behavior through an intention-revealing operation; do not make them inspect another object's state and reproduce its decision.
- Keep orchestration responsible for sequencing and failure boundaries, not for domain rules or adapter mechanics.
- Give every resource or background operation one owner for start, cancellation, cleanup, and waiting. Make failed startup unwind resources already acquired.
- Inject narrow dependencies at composition boundaries. Do not hide mutable dependencies in globals or service locators.
- Remove pass-through layers. A layer earns its place when it owns a decision, abstraction, invariant, or translation.

**Ownership test:** if two callers need the same rule, move that rule toward the object that owns the relevant knowledge. If a caller must know an implementation detail to use an API, the boundary is leaking.

## Deep modules and information hiding

A deep module offers meaningful capability through a small interface. Its implementation absorbs complexity instead of exporting configuration, storage formats, retry policy, parsing steps, or lifecycle details to every caller.

- Design the common operation first; make it hard to misuse and useful without ceremony.
- Hide representation choices behind behavior. Callers should not need to know whether data is cached, serialized, retried, pooled, or stored in a particular structure.
- Keep interfaces smaller than the implementation. A wrapper that exposes nearly every underlying operation is shallow; either deepen it or remove it.
- Generalize around stable knowledge, not hypothetical options. Avoid caller-specific methods such as `handle_button_click` in a reusable domain object when a domain operation such as `remove(range)` is sufficient.
- Keep protocol decoding, persistence mechanics, and UI policy out of a core module unless that module owns them.
- Document contracts at the boundary: preconditions, units, side effects, error behavior, and ownership of returned resources.

**Depth test:** can a caller achieve a useful outcome without configuring the module's internal decisions? If not, simplify the boundary or move the complexity inside.

## Declarative structure: tell the story of the decision

Declarative structure makes the method's intent visible in its shape. The implementation can still be imperative internally, but the public flow should expose *what* is decided and delegated rather than every low-level step.

- Make an orchestrator a short table of contents: validate, resolve, execute, publish, or fail. Name private steps after decisions or outcomes.
- Keep one principal decision in each method. Extract an independent decision only when the extracted method has a clear contract and can be understood without reading its caller.
- Use guard clauses and early returns for invalid, empty, or terminal cases. Keep normal flow at the visible indentation level.
- Tell collaborators to perform behavior; avoid asking for several fields and then making a decision from those fields in the caller.
- Separate mechanism from policy. A reusable mechanism should receive a meaningful request, while its caller chooses the domain policy only when that policy truly belongs there.
- Make failure boundaries explicit. Catch an error only where it can be translated, recovered, cleaned up, or reported with the right context.
- Avoid boolean-flag methods and parameter plumbing that make a method serve unrelated flows. Split the abstraction or introduce a typed request when the behavior genuinely differs.

A useful review question is: “Can I understand the method's decision tree by reading only its names and early exits?” If not, move knowledge to its owner, deepen a module, or extract a decision with a complete contract.

## Examples

The same design is expressed according to each language's normal idioms; these are illustrative examples, not copied production code, and none imposes a cross-language syntax rule.

### Python

```python
class ReceiptStore:
    def load_or_create(self, *, order_id: str) -> Receipt:
        receipt = self._read(order_id)
        if receipt is not None:
            return receipt
        return self._create_and_save(order_id=order_id)
```

`ReceiptStore` owns lookup and creation persistence. The caller asks for a receipt, rather than inspecting storage state or choosing serialization details.

### Go

```go
func (s *ReceiptStore) LoadOrCreate(ctx context.Context, orderID string) (Receipt, error) {
    receipt, err := s.read(ctx, orderID)
    if err != nil {
        return Receipt{}, err
    }
    if receipt != nil {
        return *receipt, nil
    }
    return s.createAndSave(ctx, orderID)
}
```

The method has a flat decision structure and keeps storage knowledge inside `ReceiptStore`; callers receive a domain result and an explicit error contract.

### TypeScript

```typescript
async loadOrCreate(orderId: string): Promise<Receipt> {
  const receipt = await this.read(orderId);
  if (receipt !== undefined) return receipt;
  return this.createAndSave(orderId);
}
```

The public method tells the story of the operation while the module owns the persistence choices. It does not expose a raw repository, cache, or serialization format merely to let callers assemble the workflow.

## Review checklist

- Is every important decision owned by the object or module with the required knowledge?
- Does the public interface hide meaningful implementation complexity?
- Does the orchestration read as named steps with explicit failure boundaries?
- Are normal paths flat, with terminal cases handled early?
- Is a proposed helper a real abstraction, or only a pass-through wrapper?
- Are resource start, cancellation, cleanup, and wait responsibilities unambiguous?
- Have language- and project-specific conventions been checked before applying this generic guidance?

## Historical context (non-normative)

The following conversation is preserved verbatim as historical context. It is not a current instruction, does not describe the current state by itself, and must not be read as an instruction to future agents. In particular, “my proposed deletion” is the historical speaker's wording, not a proposed action in this skill.

```text
You’re right. Declarative method structure is a generic engineering convention, not a Python-specific one. My proposed deletion was the wrong next step. It has not been executed.

What exists today

Location                                                                     · What it contains                                                                                                · Is it a sufficient central rule?
skills/engineering/engineering-ownership/SKILL.md                            · “Orchestration reads as named steps and explicit failure boundaries,” plus ownership and delegation principles. · Partial: a short shared statement.
skills/coding/coding-rules/SKILL.md                                          · Deep modules, information hiding, meaningful decomposition, avoiding shallow wrappers.                          · Related, but not a full declarative-structure convention.
skills/coding/declarative-method-structure/SKILL.md                         · Detailed language-independent principles, patterns, explanations, checklists, and illustrative examples. · Active generic owner.
skills/languages/python/declarative-method-structure/SKILL.md                · Python-specific syntax and contract adjustments.                                                          · Specialization read after the generic owner.
skills/languages/typescript/typescript-declarative-method-structure/SKILL.md · TypeScript-specific syntax and contract adjustments.                                                      · Specialization read after the generic owner.

Do not delete or edit language skills, the legacy declarative forwarder, coding-rules, or the index. Validate the new file with markdown/frontmatter checks if available. Report exact path, preservation of contiguous block, and tests/checks.
```
