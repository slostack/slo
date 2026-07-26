# TUI Rendering Slowdown as the Conversation Grows — Root-Cause Analysis

**Status:** Diagnosis complete. Companion to `specifications/59-tui-slow-down-fix/overview.md` (the remediation spec). This document is analysis-only; the spec is self-contained and does not depend on it.
**Component:** Slo TUI (`src/tui/`), on Textual `0.89.1` + Rich, Python 3.11.7.
**Origin:** Slo session `9df98e43-8348-4a5a-8a6a-1f70fad3c9a7` (3.3 MB event log).

> All `textual/…` and `rich/…` citations refer to the installed packages under the `slo-harness` venv.

---

## 1. Symptom

As a single conversation grows longer, (a) typing into the prompt gets laggier and (b) streamed/rendered text paints more slowly. The slowdown is a function of conversation length: a fresh session is snappy; the same operations late in a long session are slow.

## 2. Evidence

Session `9df98e43…` event log: 3,344,183 bytes, 3,152 events — 2,745 `assistant_delta`, 185 `tool_call`, 185 `tool_result`, 7 each of `run_started`/`assistant_message`/`run_completed`, 7 `user_message`.

Per-block widget composition (verified): `UserMessageBlock` = 2 widgets, `AssistantStreamBlock` = 4–5, `ToolExecutionBlock` = 5. So 7 user + 7 assistant + 185 tool ≈ **~1,000 mounted widgets** by end of session, none ever removed except `/clear`.

## 3. Root causes

### 3.1 O(N) full reflow on every keystroke and token (dominant, length-dependent)

`Static.update()` always requests a layout refresh:

```python
# textual/widgets/_static.py:104-113
def update(self, content=...):
    self._content = content
    self._visual = visualize(self, content)
    self.refresh(layout=True)
```

`refresh(layout=True)` invalidates layout up to the Screen (`textual/widget.py:3891-3896`), which performs a full compositor reflow with `visible_only=False` — descending into every mounted widget — and then calls `_size_updated` on every one:

```python
# textual/_compositor.py:386
map, widgets = self._arrange_root(parent, size, visible_only=False)
# textual/screen.py:1130-1145
layers = self._compositor.layers
for widget, (region, ...) in layers:
    widget._size_updated(region.size, virtual_size, container_size)
```

Both passes are O(total mounted widgets). Because blocks accumulate without bound (mounts at `app.py:1580/1616/1640/2024/1094`; only removal is `/clear` at `app.py:1180-1188`), N grows for the whole session, so every keystroke and every streamed token costs O(N).

### 3.2 O(m²) Rich Markdown re-parse per delta (per-answer)

`AssistantStreamBlock.append_text` (`assistant_stream_block.py:229-238`) re-renders the whole answer per delta, constructing a fresh `Markdown` from the full accumulated text; Rich parses eagerly:

```python
# rich/markdown.py:559-561
parser = MarkdownIt().enable("strikethrough").enable("table")
self.markup = markup
self.parsed = parser.parse(markup)
```

For an answer of m deltas: 1+2+…+m = O(m²) parsing plus m reflows.

### 3.3 Plain typing pays the full reflow

`on_text_area_changed` fires on every keystroke (`app.py:825-839`) and unconditionally calls the slash menu's `Static.update` (`slash_suggestion_menu.py:58`) even for empty hidden content — so ordinary prose reflows the transcript on every keystroke.

## 4. Fix direction

See `specifications/59-tui-slow-down-fix/overview.md`. In brief: (1) no-op guard on the slash menu; (2) mount-aware coalesced streaming render (bounds parse/reflow to frame rate); (3) bound the mounted widget count via a transcript window enforced at every mount site, evicting only settled blocks. Term #1 (length dependence) is fixed by the window; terms #2/#3 by the guard and coalescing.
