# Autonomous AI Sales Agent

**Point of contact:** contact@example.com

## Background

Nerdy traditionally relies on live phone agents to gather information and close individual sales. Our hypothesis is that an AI agent could meet or exceed current human sales benchmarks. If true, the implications are operational: more consistency, 24/7/365 coverage, and the ability to experiment on sales tactics at scale.

## Challenge

Build an autonomous voice AI Sales Agent. The agent gathers missing required and other leading information to assist with the sale, remembers conversation history across calls, and answers policy, objection, and competitive questions from a knowledge base. It decides in real time what to ask next, when to pivot toward close, and when to escalate low-confidence turns or high-stakes moments like pricing concessions.

Observe and track the agent through typical sales KPIs. Build iterative loops of controlled experiments and autoresearch on anything from question phrasing, sequencing, and inbound/outbound tactics, with prompts, playbooks, and rebuttals.

## Minimum Requirements

### Conversation
- Real-time bidirectional voice (STT+TTS or STS) with latency low enough for natural turn-taking and barge-in
- Handle leads with full prior info, partial info, or none, carrying over any existing conversation history
- Consistent agent persona

### Discovery & Knowledge
- Prioritized script of required and leading questions, with dynamic ordering and skip-when-already-known
- Knowledge base lookup for policy, objection, and competitive answers, with grounded responses (no hallucinated facts)

### Decisioning
- Real-time choice of next question, when to pivot toward close, and when to escalate

### Observability
- Full transcript and outcome captured per call
- Each call tagged with the version used, so performance can be attributed
- Dashboards for tracking each agent against typical sales KPIs

## Recursive Improvement Requirement

Your system must demonstrate at least one meaningful improvement loop. A meaningful loop measurably moves a sales KPI from a documented baseline through variant generation, controlled experimentation, and a decision to promote or retire. You may choose how automated the loop is: it could suggest changes for a human to approve, auto-promote low-stakes variants while escalating bigger ones, or modify prompts and playbooks end-to-end without human review. Beyond prompts, you could fine-tune the underlying model itself.

To power the recursive improvement loop, you will need to generate synthetic data to communicate with your agent, for example through AlphaGo-style self-play, using simulated prospects. Additionally, a small database of PII-substituted sales transcripts will be provided to help train or refine likely personas. You may also ground the agent in sales books, methodology guides, or other materials, either by indexing them in the knowledge base or by using them as additional training signal.

Start by picking a single dimension to prove the pattern: a question's phrasing, an objection rebuttal, a sequencing rule, agent persona, or a playbook, and document before and after.

## Deliverables

- **End-to-end functional**, not mockups or video. The agent should handle a complete discovery-to-close conversation over a live voice channel (phone, WhatsApp, or web for demo purposes).
- **Observable:** transcripts, decisions made (next question, pivot, escalate), and the KPIs you chose to track are accessible through a dashboard, not buried in logs.
- **Recursive improvement loops run**, not just diagrammed. Show before-and-after evidence.
- **Documentation:** failure mode report, recursive improvement description, decision log, research notes, and limitations memo.

## What We Are Evaluating

We are evaluating whether you can build a voice sales agent that actually sells. That means designing synthetic prospects honest enough to expose its weaknesses, and running an improvement loop that moves a meaningful KPI rather than a flattering one.

A weak submission spins up a swarm of obedient synthetic leads who always agree and reports a rising win rate, but fails when trialed by a real human. A strong submission handles prospects who hesitate, push back on price, and disqualify themselves, while showing the agent getting measurably better against them. The best submissions will sound like a call that a real sales agent could be on the other end of, not a script reader with a voice.
