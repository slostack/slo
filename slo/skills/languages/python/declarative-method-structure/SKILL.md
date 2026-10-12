---
name: python-declarative-method-structure
description: 'Python: language-specific syntax and contracts for the shared Tell, don''t ask and coherent-decomposition rule.'
when_to_use: For Python projects only. Read after the generic declarative-method-structure owner.
group: languages
kind: skill
source_prompt: declarative-method-structure.md
---

# Python Declarative Method Structure

## Skill summary

This is the Python specialization of the shared owner at
`skills/coding/declarative-method-structure/SKILL.md`. Read that owner first for
coherent decomposition, one decision per method, Tell, Don't Ask, flat control
flow, meaningful examples, testing boundaries, and the generic review
checklist. This file does not restate those lessons.

This specialization owns Python-specific syntax and obligations: explicit
parameter and return annotations, Google-style method docstrings where required,
keyword arguments at multi-argument call sites, Python lookup/strategy idioms,
truthful nullable returns, and the historical Python refactoring signal of
approximately **8 lines of substantive logic**. The signal is a review prompt,
not a formatter quota; the generic meaningful-decomposition rule prevails over
mechanical splitting.

## Examples

- Use this file when a Python method needs the language-specific form of the shared rule.
- Use it for Python annotations, docstrings, keyword-call contracts, lookup maps, or the ~8-line signal.
- Use the generic owner for the full before/after teaching patterns and cross-language semantics.

## Guidance

**Applicability:** Python only. Framework-specific sections apply only when that
stack is present. Load `skills/languages/python/python-conventions/SKILL.md` and
the applicable Python testing recipe. A Python project does not acquire
FastAPI, SQLAlchemy, Celery, DBOS, or another framework by reading this skill.
Applicable framework, security, persistence, and test rules remain in force.

### Python contracts

Use explicit parameter and return annotations, including truthful nullable
returns. Use Google-style docstrings on methods/functions where the Python
conventions require them. Calls with multiple meaningful arguments use keyword
arguments. These are Python contracts in addition to the shared design rule;
they are not reasons to make every helper public.

```python
async def process_order(order_id: str) -> None:
    """Charge a validated pending order and send its confirmation."""
    order = await self._load_and_validate_order(order_id=order_id)
    await self._charge_customer(order=order)
    await self._send_confirmation(order=order)


def _validate_order_amount(order: Order) -> None:
    """Reject an order whose amount is not positive."""
    if order.total_amount <= 0:
        raise ValueError("Order amount must be positive")
```

The generic owner contains the complete validation-chain example and its
reasoning; this excerpt only demonstrates Python signatures, docstrings, and
keyword calls.

### Python lookup and strategy idioms

For independently extensible alternatives, a typed dictionary can be the
Python expression of a lookup boundary. Keep a small, closed choice as a
conditional when that is clearer. Use `collections.abc.Callable` and concrete
container types when the callable contract matters:

```python
from collections.abc import Awaitable, Callable

Formatter = Callable[[Report], Awaitable[str]]


def _get_formatter(self, report_type: str) -> Formatter:
    """Return one formatter or reject an unsupported report type."""
    formatters: dict[str, Formatter] = {
        "pdf": self._format_as_pdf,
        "json": self._format_as_json,
    }
    formatter = formatters.get(report_type)
    if formatter is None:
        raise ValueError(f"Unsupported report type: {report_type}")
    return formatter
```

The generic owner retains the full long-chain before/after example. Do not
copy its language-independent explanation here.

### Python decomposition signal

Around **8 lines of substantive logic** is a Python review signal. Do not count
docstrings, required annotations, or a simple guard as a reason to split. Do
extract when the method owns multiple unrelated policies or when the helper has
a clear input, output, owner, and independently testable contract. A shorter
method still needs extraction if it makes multiple decisions; a longer method
may remain intact when it is one coherent operation and splitting would create
shallow fragments.

### Python-specific review triggers

| Python signal | Action |
|---|---|
| More than one normal level of conditional nesting | Use guard clauses or delegate to a named owner. |
| Approximately 8 lines of substantive logic | Review for a clean independent abstraction; do not split mechanically. |
| Multiple meaningful call arguments | Use keyword arguments. |
| Missing/ambiguous parameter or return type | Add an explicit annotation, including `Optional`/nullable intent. |
| Method/function requiring project documentation | Add the applicable Google-style docstring. |
| Extensible alternatives | Use a typed lookup/strategy boundary. |
| Caller reads another object's policy fields | Tell the owning object to act. |

## Python checklist

- [ ] Did I read `skills/coding/declarative-method-structure/SKILL.md` first?
- [ ] Are parameters and returns explicitly and truthfully typed?
- [ ] Are meaningful multi-argument calls keyword-based?
- [ ] Do methods requiring project documentation have Google-style docstrings?
- [ ] Is approximately 8 lines used as a review signal rather than an artificial quota?
- [ ] Does every extracted helper form a meaningful, independently understandable abstraction?
- [ ] Did I keep framework, persistence, security, and test obligations in their applicable owners?
- [ ] Do tests cover each Python decision and failure boundary at the correct layer?
