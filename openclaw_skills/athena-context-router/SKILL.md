---
name: athena-context-router
description: Consult Ravi's mirrored Athena context before answering requests that depend on prior validated work, cross-session memory, case studies, stable preferences, dossiers, timelines, or astrology. Use when Ravi asks what is already known, wants continuity with previous work, or needs validated chronology instead of only fresh synthesis.
---

# Athena Context Router

## Overview

Use this skill when the answer depends on Athena-backed context rather than only the current chat.
This skill keeps the lookup narrow: prefer canonical and memory-bank files first, then case studies, then session logs only if exact chronology matters.

## Workflow

1. Read `athena/README.md` first for the mirror layout and retrieval order.
2. Start with the narrowest high-signal file that can answer the question:
   - `athena/CANONICAL.md`
   - `athena/memory_bank/activeContext.md`
   - `athena/memory_bank/userContext.md`
   - `athena/memory_bank/constraints.md`
   - `athena/memory_bank/productContext.md`
   - `athena/memory_bank/systemPatterns.md`
3. If Ravi asks for reusable precedent or prior validated patterns, read `athena/memories/case_studies/`.
4. Only read `athena/memories/session_logs/` when chronology, provenance, or an exact prior statement matters.
5. In the response, make the distinction clear:
   - stable memory
   - validated prior case
   - exact session evidence
   - fresh inference

## Guardrails

- Do not claim Athena was consulted unless you actually read Athena mirror files.
- Prefer `CANONICAL.md` and `memory_bank/` over session logs when they conflict.
- Do not load all Athena files by default; choose the narrowest useful subset.
- For astrology requests, keep separate:
  - chart fact
  - validated event
  - inference

## Good Requests

- `What do we already know about this client from prior work?`
- `Check Athena first and tell me the stable constraints before answering.`
- `Use Athena context and summarize the relevant case studies for this situation.`
- `What is the validated timeline here? Use Athena, not just chat memory.`
- `For this astrology question, use Athena case-study memory first.`
