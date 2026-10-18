"""Detached-workflow TUI receive-path namespace (spec 57.a.5 refactor).

Layers, in dependency order:

- ``dao.py`` — typed lifecycle payloads, UI-effect/result objects, and
  parsing/validation helpers. No Textual imports, no filesystem or
  visualizer side effects.
- ``service.py`` — ``DetachedWorkflowAppService`` coordinates handle-store
  reconcile, legal durable transitions, the live-state cache, and the
  translation of inbox lifecycle messages / ``launch_workflow`` tool
  results into typed UI effects. No UI imports.
- ``renderer.py`` — ``DetachedWorkflowRenderer`` consumes the typed effects,
  owns visualizer launch de-duplication, and emits transcript notices.
  It is the only layer allowed to talk to ``VisualizerLauncher`` and the
  transcript notice surface.
- ``transcript_renderer.py`` — ``WorkflowTranscriptRenderer`` renders public
  transcript entries for both the external visualizer and the in-app progress
  view (feature 94 a.3). Presentation only; it never scrolls or reads files.
"""
