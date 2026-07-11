# Slo Repo Conventions

- Read `AGENTS.md` first for any code, architecture, workflow, or testing task in this repository.
- If the user says **"dynamic workflows"** or the misspelling **"dyanmic workflows"**, treat that as an explicit request to use the orchestrator / headless workflow path: launch a Slo orchestrator that launches multiple Slo agents to execute the workflow's parts.
- Outside that shorthand, preserve the normal policy: only use orchestrator / `spawn_sub_agents` execution when the user explicitly asks for it.
