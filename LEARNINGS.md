# Learnings

## Specification writing

### Explain the mechanism, not just the promised improvement

**Context:** The skill-selection specification did not clearly show what code would select skills more accurately than the existing model-driven discovery.
**Insight:** Name the exact proposed function and file, its caller, inputs, selection rules, outputs, and ambiguity handling. Explain where task facts come from. Show one old-versus-new example, including rejected skills, and the tests or measurements that demonstrate improvement; distinguish proposed behavior from implemented or measured behavior.
**Why it matters:** A registry or metadata schema alone does not explain how an agent chooses the right skill or prove greater accuracy.

### Be concise without removing implementation detail

**Context:** Specification drafts obscured the requested behavior with unexplained jargon and repeated process descriptions.
**Insight:** Write for the human reader first: explain the current problem, show a concrete example of the change, then introduce the exact code and tests. Use short, direct sentences; define necessary technical terms before using them. Remove repetition and administrative narration, not required implementation detail. Apply this to every child specification as well as the overview.
**Why it matters:** A long document is not necessarily a clear or implementable specification; unreadable explanations violate the vendored specification skill's existing requirements.
