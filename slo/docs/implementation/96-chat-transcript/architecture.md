# ChatTranscript architecture after main integration

ChatTranscript is a mounted Textual presentation component, not an agent, session,
persistence owner or LLM client. SloTUI constructs one inert component, then mounts
it, hydrates persisted history before subscribing, and forwards parent events.

## Source tree

```text
src/
├── cli/                         # CLI parsing and runtime/session assembly
├── agents/
│   ├── base.py                  # Model/provider construction
│   └── slo_agent/
│       ├── sessions/service.py  # Run admission, history, subscriptions, lifecycle
│       ├── agent.py             # Agent inference/tool loop
│       ├── graph/service.py     # Model/tool graph and event bridge
│       ├── events/              # Normalized AgentStreamEventDAO
│       ├── history/             # Canonical persisted history and replay
│       └── orchestrator/        # Managed children/workflow execution
└── tui/
    ├── app.py                   # SloTUI: input, execution, focus, session lifetime
    ├── components/chat_transcript/
    │   ├── component.py         # ChatTranscript + TranscriptScroll; presentation lifetime
    │   ├── css.tcss             # Component-scoped packaged styles
    │   └── adapters/
    │       ├── transcript.py    # TranscriptNoticeDisplayAdapter: notices/logical copy
    │       ├── workflow_notice.py # Workflow notices into main transcript
    │       └── workflow_progress.py # App-owned progress presentation adapter
    ├── transcript_projector.py  # TranscriptProjectionAdapter: events → widgets
    ├── widgets/                 # User, answer, thinking, tool, queue, fleet widgets
    └── workflows/               # Observation service/coordinator, modal, renderer
```

`workflow_progress.py` is physically under the component adapters directory but
its lifetime and workflow decisions remain app-owned. It does not belong to the
foreground transcript event projector.

## Mounted tree

```text
SloTUI
├── Header
├── #chat-shell
│   ├── ChatTranscript
│   │   └── TranscriptScroll (#transcript-scroll)
│   │       ├── #transcript-content
│   │       │   ├── Earlier-history summary / prepend boundary
│   │       │   ├── Turn separators + UserMessageBlock
│   │       │   ├── AssistantStreamThinkingBlock
│   │       │   ├── AssistantStreamBlock
│   │       │   ├── ToolExecutionBlock / SteeringPendingBlock
│   │       │   └── Literal notices
│   │       └── Tree-export widgets (outside ordinary transcript window/clear)
│   ├── #status-region (suggestions, activity presentation)
│   ├── QueuedPromptBlock (when present; immediately before input)
│   ├── PromptInput
│   ├── SubAgentFleetPanel
│   └── UsageStatusBar
└── Footer
    [Progress/auth/confirmation screens are separate modal screens]
```

## User input → LLM → rendered response

```text
PromptInput.Submitted
  → SloTUI routes slash commands or admits/queues an ordinary prompt
  → ChatTranscript.echo_user(text=...)              [presentation only]
  → SloTUI registers _run_prompt under its submission lock
  → SloAgentSession.invoke(text=...)
      → model preparation, context/history and run ownership
      → SloAgent / graph
          → provider SDK → LLM streaming response
          ↔ tool execution and subsequent model steps
      → normalized AgentStreamEventDAO + canonical history handling
      → session subscriber: SloTUI._render_event
          ├── status/recovery/compaction → app-owned activity/status
          ├── child/workflow events → app-owned workflow observation
          └── parent transcript event → ChatTranscript.present_event
                → lifecycle admission + mutation serialization
                → TranscriptProjectionAdapter.project
                → answer/thinking/tool widgets update
                → pre-mutation FollowSnapshotDAO / Rendered notification
                → viewport settlement and Textual layout/compositor paint
```

`_run_prompt` drains the async generator; rendering occurs through the session's
registered event subscriber, not a second rendering pass over generator yields.
The session owns persistence; transcript logical-copy lines are not canonical
conversation history. Resume reads real history through the borrowed reader and
uses the same projector/widgets without rewriting that history.

## Ownership and merge decisions

- ChatTranscript owns initial newest-30 hydration, older batches, logical cursor,
  500-widget window with protected newest ten/live blocks, selection-compatible
  widgets, native navigation, snapshots and hide/show reading restoration.
- SessionFactory remains injectable; upstream prepares the replacement before
  retiring the old session. Adoption binds the existing component to the new reader.
- Upstream Herdr shutdown/observation/inbox lifetime protections remain app-owned.
  Replay accepts a captured-owner predicate and revalidates after reads, each mount
  and the summary await. Component unmount joins its own cleanup; app shutdown does
  not deadlock by waiting for a blocked replay publisher under its mutation lock.
- Visualizer execution retains upstream asynchronous scheduling and cancellation;
  injected launch behavior remains available. Upstream truthful notice wording,
  failed-launch retries and workflow visibility semantics are retained.
- Main consolidated/deleted AGENTS.md and docs/RESEARCH.md. This document preserves
  the extraction-specific owner map instead of resurrecting removed documentation.

No intentional chat UI redesign is introduced. Upstream changes (workflow wording,
visibility and external reporting) remain present; their visible differences belong
to main, not the transcript extraction.
