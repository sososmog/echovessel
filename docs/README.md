# EchoVessel Documentation

Welcome. EchoVessel is a **local-first digital persona engine** with long-term memory, voice, and pluggable channels.

This documentation has two parallel language trees. Pick whichever you prefer — they cover the same material.

- 🇬🇧 [**English**](./en/README.md)
- 🇨🇳 [**中文**](./zh/README.md)

---

## For different readers

- **Just heard about EchoVessel** → start with the landing page in your language
- **Want to install and run it** → the landing page has a quickstart; `configuration.md` has the full config reference
- **Want the 10-minute architecture tour** → 🗺 [**`architecture.html`**](./architecture.html) — one-page visual deep-dive covering module layers, memory L1-L4, message flow, cross-channel SSE, HTTP surface, iron rules, release timeline
- **Want the simplest possible mental model of memory** → 🧠 [**`memory/layers.html`**](./memory/layers.html) — one SVG figure · 4 layers · how they connect · credits to Stanford Generative Agents for the scoring formula
- **Want to see how memory layers *wake up* during a turn** → 🔄 [**`architecture-flow.html`**](./architecture-flow.html) — the "nervous system" companion: step-by-step activation, 8-column sequence diagram, real story trace, read/write matrix, feedback loops
- **Want to understand how it works** → each module has its own page(`memory.md`, `voice.md`, `channels.md`, `proactive.md`, `runtime.md`, `import.md`)
- **Want to extend it (custom channel / LLM provider / prompt)** → each module page includes a "How to Extend" section
- **Want to contribute to the core** → `contributing.md`
