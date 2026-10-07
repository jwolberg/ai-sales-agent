# PRD: Autonomous AI Sales Agent

> **Superseded scope (2026-05-28):** the project narrowed from a full discovery-to-close sales
> agent to a two-option voice **intent router** (test prep vs. tutoring → leaf → price quote). This
> PRD is retained as history of the original scope. Current requirements live in
> `docs/brainstorms/intent-router-agent-requirements.md`; the active plan is
> `docs/BUILD_PLAN_INTENT_ROUTER.md`. See `docs/decision-log.md` (D-13).

## 1. Product Summary

Build an autonomous real-time voice AI sales agent for a tutoring company that can conduct a complete discovery-to-close sales conversation with prospective tutoring customers.

The agent should gather missing required information, use prior conversation history, answer questions from a grounded knowledge base, handle objections, decide when to pivot toward close, and escalate high-risk or low-confidence situations. The system must be observable through transcripts, decision traces, KPI dashboards, and versioned experiment results.

The product is not just a voice demo. It is a measurable sales system with an improvement loop that tests whether the agent can get better over time.

## 2. Background

The business currently relies on live phone sales agents to qualify leads, gather information, answer questions, handle objections, and close individual sales. Human agents create operational constraints: limited hours, variable quality, training overhead, and slower experimentation cycles.

The core hypothesis is:

> An autonomous AI voice sales agent can meet or exceed human sales benchmarks for selected lead types while providing greater consistency, availability, observability, and experimentation velocity.

If validated, this could improve sales coverage, reduce operational load, and create a scalable experimentation platform for scripts, personas, objection handling, and closing tactics.

## 3. Goals

### Primary Goal

Build an end-to-end functional voice sales agent that can complete a realistic tutoring sales conversation from discovery through close or escalation.

### Secondary Goals

- Demonstrate natural real-time voice interaction with interruption handling.
- Personalize conversations using known lead data and prior call history.
- Answer policy, pricing, objection, and competitive questions using a grounded knowledge base.
- Capture all transcripts, decisions, outcomes, and KPIs in a dashboard.
- Run at least one measurable recursive improvement loop using synthetic prospects and before/after evidence.

## 4. Non-Goals

This MVP will not attempt to:

- Replace all human sales agents across every lead type.
- Support unrestricted pricing negotiation or unauthorized discounts.
- Guarantee sale completion for all prospects.
- Fine-tune a foundation model unless time permits.
- Build a full production CRM integration.
- Build a full outbound dialer system beyond what is needed for demo/testing.
- Handle regulated payment processing unless a safe demo checkout path is provided.

## 5. Target Users

### 5.1 Prospective Customer

A parent, student, or adult learner interested in tutoring services.

Common examples:

- Parent looking for math tutoring for a child.
- High school student preparing for SAT/ACT.
- College student needing course support.
- Adult learner seeking test prep, language, or professional tutoring.

### 5.2 Sales Operator / Manager

A sales leader at the business who wants to monitor agent performance, understand outcomes, review transcripts, and compare experiment variants.

### 5.3 Human Sales Agent / Escalation Handler

A human operator who receives escalated conversations when the AI encounters a high-risk or low-confidence situation.

## 6. Core Use Cases

### Use Case 1: Lead With Full Prior Info

The system receives a lead profile with known student name, grade level, subject, contact history, and prior objections. The agent should skip known questions, confirm key details naturally, and continue from prior context.

### Use Case 2: Lead With Partial Info

The system receives partial lead data, such as subject and grade level, but lacks urgency, goals, schedule, decision-maker status, or budget sensitivity. The agent should prioritize missing required fields while keeping the conversation natural.

### Use Case 3: Lead With No Info

The system receives only a phone number or web voice session. The agent should begin discovery from scratch and progressively collect the minimum required information.

### Use Case 4: Objection Handling

The prospect raises objections such as:

- "It's too expensive."
- "I need to talk to my spouse."
- "We are comparing Wyzant / local tutors / school support."
- "Can we get a discount?"
- "How do I know the tutor will be good?"
- "We tried tutoring before and it did not work."

The agent must answer using approved knowledge and playbooks, not hallucinated claims.

### Use Case 5: Close or Escalate

The agent decides whether to:

- Ask another discovery question.
- Summarize fit.
- Recommend next step.
- Ask for commitment.
- Escalate to human.
- End the call as unqualified.

## 7. MVP Scope

The MVP should support a single sales flow:

> Parent or student inquiring about one-on-one tutoring or test prep.

The agent must be able to:

- Conduct a live voice conversation through a web demo, phone, or WhatsApp.
- Retrieve known lead information.
- Maintain memory across calls.
- Ask required discovery questions.
- Dynamically skip questions already answered.
- Use a knowledge base for policy, objection, and competitor responses.
- Decide when to close or escalate.
- Record transcript, decisions, KPI events, and final outcome.
- Display results in a dashboard.
- Run a recursive improvement loop for one selected sales behavior.

## 8. Selected Recursive Improvement Dimension

For the MVP, the improvement loop will focus on:

> **Price objection rebuttal strategy.**

Reason: price sensitivity is common, high-impact, and directly tied to sales conversion. It is also a strong test of whether the agent can sound like a real salesperson instead of a script reader.

### Baseline Variant

The baseline agent responds to price objections with a generic value statement.

Example behavior:

> "I understand price is important. Acme Tutoring offers personalized support from expert tutors, and many families find the investment worthwhile."

### Variant Candidates

The system will generate and test alternative rebuttal styles, such as:

- Empathy-first value framing
- Outcome-cost framing
- Risk-reversal framing
- Comparison-to-alternatives framing
- Diagnostic reframing, where the agent asks what outcome would make tutoring worth it

### Primary KPI for This Loop

**Objection Recovery Rate**

Definition:

> Percentage of calls where a price objection occurs and the prospect still agrees to a next step, such as scheduling a consultation, accepting a recommended plan, or continuing the buying conversation.

### Secondary KPIs

- Call continuation after objection
- Sentiment after objection
- Close attempt success rate
- Escalation rate
- Prospect frustration rate
- Average turns to recovery

### Promotion Rule

A variant can be promoted if it:

- Improves objection recovery rate versus baseline.
- Does not increase prospect frustration beyond an allowed threshold.
- Does not increase unsupported claims or hallucinated policy statements.
- Performs across multiple synthetic prospect personas, not just easy leads.

## 9. Functional Requirements

### 9.1 Voice Conversation

#### Requirement VC-1: Real-Time Bidirectional Voice

The agent must support real-time voice input and output using either:

- STT + LLM + TTS pipeline, or
- Speech-to-speech model.

The conversation must feel natural enough for turn-taking.

#### Requirement VC-2: Barge-In

The user must be able to interrupt the agent while it is speaking.

When interrupted, the agent should:

- Stop speaking.
- Process the new user input.
- Continue from the updated context.

#### Requirement VC-3: Latency Target

The system should target:

- First audible response: under 2 seconds for normal turns.
- Interruption handling: under 1 second to stop playback.
- Knowledge-base-supported answer: under 4 seconds when retrieval is required.

#### Requirement VC-4: Consistent Persona

The agent must maintain a consistent persona:

- Professional
- Warm
- Consultative
- Confident but not pushy
- Focused on the student's goals
- Transparent when it needs to escalate

The agent should not sound like a rigid script reader.

### 9.2 Lead Context and Memory

#### Requirement LM-1: Lead Profile Support

The system must support lead records with:

- Lead ID
- Contact name
- Student name, if known
- Relationship to student
- Subject or test area
- Grade level or learner type
- Known goals
- Prior call summary
- Prior objections
- Known schedule constraints
- Known budget sensitivity
- Current lifecycle status

#### Requirement LM-2: Partial Information Handling

The agent must detect which required fields are missing and ask for them naturally.

#### Requirement LM-3: Skip Known Information

The agent must not repeatedly ask for information already known unless confirmation is needed.

Example:

> "I see this is for 8th grade algebra. Is that still the main area you're looking for help with?"

#### Requirement LM-4: Cross-Call Memory

The agent must remember previous conversation history across calls.

At minimum, the system must persist:

- Call summary
- Required fields collected
- Objections raised
- Buying signals
- Disqualification signals
- Next-step status
- Agent version used
- Experiment variant used

### 9.3 Discovery Flow

#### Requirement DF-1: Required Questions

The agent must gather the following minimum discovery information when missing:

- Who needs tutoring?
- Subject, course, or test area.
- Grade level or learner stage.
- Current challenge or reason for seeking help.
- Desired outcome.
- Urgency or timeline.
- Prior tutoring experience, if relevant.
- Schedule availability.
- Decision-maker status.
- Readiness for next step.

#### Requirement DF-2: Leading Questions

The agent should also gather leading sales information when appropriate:

- Pain severity.
- Consequences of not solving the problem.
- Motivation level.
- Competing options being considered.
- Budget sensitivity.
- Preferred tutor style.
- Parent/student confidence level.
- Success criteria.

#### Requirement DF-3: Dynamic Ordering

The agent must decide the next best question based on:

- Known lead data
- Missing required fields
- Prospect emotional state
- Buying signals
- Objections
- Conversation stage
- Prior call history

#### Requirement DF-4: Natural Conversation

The agent must avoid interrogating the prospect with a checklist. It should group questions conversationally and summarize context when useful.

### 9.4 Knowledge Base

#### Requirement KB-1: Grounded Answers

The agent must answer policy, objection, and competitive questions only using approved knowledge-base content.

#### Requirement KB-2: Supported Knowledge Types

The knowledge base should include:

- Company offering overview.
- Tutoring formats.
- Tutor matching process.
- Scheduling policies.
- Pricing rules or approved pricing language.
- Refund or satisfaction policies, if provided.
- Competitive comparison guidance.
- Common objection rebuttals.
- Escalation policies.
- Compliance and prohibited claims.

#### Requirement KB-3: Source-Aware Responses

The agent should internally track which knowledge-base source supported each answer.

The user-facing response does not need formal citations in voice, but the dashboard should show retrieval sources for auditability.

#### Requirement KB-4: No Hallucinated Facts

If the knowledge base does not contain enough information, the agent must say so and either ask a clarifying question or escalate.

Example:

> "I want to make sure I give you the accurate answer on that. Let me connect you with someone who can confirm the details."

### 9.5 Decisioning

#### Requirement DE-1: Next Action Selection

After each user turn, the agent must choose one of the following actions:

- Ask required discovery question.
- Ask leading discovery question.
- Answer knowledge question.
- Handle objection.
- Summarize fit.
- Pivot toward close.
- Attempt close.
- Escalate to human.
- Disqualify lead.
- End call.

#### Requirement DE-2: Decision Trace

Each decision must be logged with:

- Conversation stage
- Selected action
- Reason
- Confidence level
- Missing required fields
- Detected intent
- Detected objection, if any
- Escalation risk, if any
- Agent version
- Experiment variant

#### Requirement DE-3: Close Criteria

The agent may pivot toward close when:

- Required discovery fields are complete or sufficient.
- A clear student need exists.
- The prospect has shown interest or buying intent.
- No unresolved high-risk objection remains.
- The agent has enough confidence to recommend a next step.

#### Requirement DE-4: Escalation Criteria

The agent must escalate when:

- User requests a human.
- User asks for unauthorized price concessions.
- User asks a policy question not covered by KB.
- User becomes angry or confused.
- User raises legal, safety, or privacy concerns.
- Confidence falls below threshold.
- The agent detects a high-value lead needing human handling.
- The user asks to complete a transaction that requires human or secure payment handling outside MVP scope.

### 9.6 Closing Flow

#### Requirement CF-1: Fit Summary

Before closing, the agent should summarize the prospect's situation.

Example:

> "So it sounds like your daughter is in 8th grade algebra, she's been losing confidence after the last few tests, and you're hoping to get support in place before the next unit. Based on that, personalized tutoring sounds like a strong fit."

#### Requirement CF-2: Recommended Next Step

The agent should recommend one clear next step, such as:

- Schedule a consultation.
- Match with a tutor.
- Start enrollment.
- Transfer to a human specialist.
- Send follow-up information.

#### Requirement CF-3: Close Attempt Logging

Every close attempt must be logged with:

- Close type
- Timing
- Preceding objection state
- User response
- Outcome

## 10. Observability Requirements

### 10.1 Call Record

Each call must generate a call record containing:

- Call ID
- Lead ID
- Timestamp
- Agent version
- Experiment variant
- Channel
- Full transcript
- Audio recording link, if available
- Conversation summary
- Final outcome
- KPI events
- Decision trace
- Escalations
- Knowledge-base retrievals
- Error events

### 10.2 Dashboard

The dashboard must show:

- Total calls.
- Calls by agent version.
- Calls by experiment variant.
- Completion rate.
- Qualification rate.
- Close attempt rate.
- Close success rate.
- Objection rate.
- Objection recovery rate.
- Escalation rate.
- Average call duration.
- Average turns per call.
- Knowledge-base fallback rate.
- Low-confidence turn rate.
- Human review flags.

### 10.3 Transcript Review

The dashboard must allow review of individual calls with:

- Full transcript
- Agent decisions per turn
- Detected intent
- Detected objections
- Retrieved knowledge snippets
- Final outcome
- KPI tags

### 10.4 Version Attribution

Every call must be attributable to:

- Agent prompt version
- Playbook version
- Knowledge-base version
- Model version
- Experiment variant
- Voice configuration

## 11. Recursive Improvement Loop

### 11.1 Objective

Demonstrate that the system can measurably improve a sales KPI through controlled experimentation.

The MVP loop will improve price objection handling.

### 11.2 Loop Steps

#### Step 1: Establish Baseline

Run the baseline agent against a fixed set of synthetic prospects that include price objections.

Capture:

- Objection recovery rate
- Close attempt success
- Escalation rate
- Frustration score
- Unsupported claim rate

#### Step 2: Generate Variants

Generate several alternate price objection rebuttal strategies.

Each variant should define:

- Rebuttal language
- When to use it
- When not to use it
- Escalation trigger
- Compliance constraints

#### Step 3: Controlled Experiment

Run each variant against the same or equivalent synthetic prospect set.

Use consistent lead personas and randomized ordering to reduce bias.

#### Step 4: Evaluate Results

Compare each variant against baseline using selected KPIs.

#### Step 5: Promote or Retire

Promote a variant only if it improves the primary KPI without violating guardrails.

Retire variants that:

- Increase frustration
- Make unsupported claims
- Sound manipulative
- Escalate too often
- Fail against skeptical prospects

#### Step 6: Document Before and After

Produce a recursive improvement report showing:

- Baseline performance
- Variant performance
- Example transcripts
- Decision rationale
- Promotion or retirement decision
- Limitations

## 12. Synthetic Prospect System

### 12.1 Purpose

Synthetic prospects are used to test the agent honestly before exposing it to humans.

They must be designed to reveal weaknesses, not flatter the system.

### 12.2 Prospect Persona Types

The system should include at least the following synthetic personas:

**Persona 1: Motivated Parent**
- Clear need
- High urgency
- Moderate price sensitivity
- Likely to convert if trust is built

**Persona 2: Skeptical Parent**
- Has tried tutoring before
- Questions whether it will work
- Pushes for proof and guarantees

**Persona 3: Price-Sensitive Parent**
- Interested but concerned about cost
- Compares against cheaper alternatives
- May ask for discounts

**Persona 4: Busy Parent**
- Limited time
- Wants fast answers
- Low patience for long discovery

**Persona 5: Competitive Shopper**
- Comparing us to alternatives
- Asks direct competitive questions

**Persona 6: Poor Fit / Disqualified Lead**
- Unclear need
- Unrealistic expectations
- Not ready to buy
- Tests whether the agent can avoid forcing a close

### 12.3 Synthetic Prospect Behavior Requirements

Synthetic prospects must:

- Hesitate.
- Interrupt.
- Ask follow-up questions.
- Provide partial answers.
- Raise realistic objections.
- Occasionally disqualify themselves.
- Resist overly pushy closing.
- Reward helpful, consultative selling.

## 13. Data Requirements

### 13.1 Input Data

The system should support:

- Lead profile data
- Prior call summaries
- PII-substituted historical sales transcripts
- Knowledge-base documents
- Sales playbooks
- Objection-handling guides
- Synthetic persona definitions
- Experiment configuration

### 13.2 Stored Data

The system must store:

- Lead records
- Conversation memory
- Call transcripts
- Agent decisions
- KPI events
- Experiment assignments
- Variant definitions
- Evaluation results
- Escalation records

### 13.3 Privacy and PII

The system must treat sales conversations as sensitive.

Requirements:

- Use PII-substituted training transcripts where provided.
- Avoid exposing raw PII in experiment reports.
- Redact sensitive fields in dashboard views when appropriate.
- Log only necessary information.
- Separate production lead data from synthetic test data.
- Ensure clear labeling of synthetic versus real calls.

## 14. Suggested System Architecture

### 14.1 Components

**Voice Interface**

Supports live bidirectional conversation through web, phone, or WhatsApp.

Possible implementation options:

- WebRTC browser demo
- Twilio phone integration
- WhatsApp voice integration if available
- Realtime speech model

**Conversation Orchestrator**

Responsible for:

- Conversation state
- Lead memory
- Next action selection
- Tool calls
- Escalation decisions
- Prompt assembly
- Decision logging

**Knowledge Retrieval Service**

Responsible for:

- Indexing approved KB documents
- Retrieving relevant facts
- Returning grounded snippets
- Flagging unsupported answers

**Sales Policy Engine**

Responsible for:

- Required fields
- Close criteria
- Escalation rules
- Pricing guardrails
- Compliance constraints

**Experiment Engine**

Responsible for:

- Variant assignment
- Prompt/playbook versioning
- Synthetic prospect test runs
- KPI comparison
- Promotion/retirement decisions

**Synthetic Prospect Simulator**

Responsible for:

- Running simulated calls
- Generating realistic prospect behavior
- Scoring agent performance
- Stress-testing objections

**Dashboard**

Responsible for:

- KPI visualization
- Transcript review
- Decision trace display
- Experiment results
- Failure mode reporting

**Database**

Stores:

- Leads
- Calls
- Transcripts
- Decisions
- Experiments
- Variants
- KPI events
- KB metadata

## 15. Suggested Data Model

### Lead

- lead_id
- contact_name
- student_name
- relationship_to_student
- subject
- grade_level
- goal
- urgency
- schedule_constraints
- decision_maker_status
- budget_sensitivity
- prior_objections
- prior_summary
- status
- created_at
- updated_at

### Call

- call_id
- lead_id
- channel
- started_at
- ended_at
- agent_version
- playbook_version
- kb_version
- model_version
- experiment_id
- variant_id
- outcome
- summary
- recording_url

### Turn

- turn_id
- call_id
- speaker
- text
- timestamp
- detected_intent
- detected_objection
- sentiment
- confidence

### Decision

- decision_id
- call_id
- turn_id
- stage
- selected_action
- reason
- confidence
- missing_fields
- escalation_risk
- kb_sources_used
- created_at

### KPI Event

- event_id
- call_id
- event_type
- event_value
- metadata
- created_at

### Experiment

- experiment_id
- name
- dimension
- baseline_variant_id
- status
- primary_kpi
- guardrail_kpis
- start_date
- end_date
- decision

### Variant

- variant_id
- experiment_id
- name
- description
- prompt_delta
- playbook_delta
- status
- created_at
- promoted_at
- retired_at

## 16. KPI Definitions

### Primary MVP KPIs

| KPI | Definition |
| --- | --- |
| Discovery Completion Rate | Percentage of calls where required fields are collected |
| Qualified Lead Rate | Percentage of calls where the lead is determined to be a fit |
| Close Attempt Rate | Percentage of qualified calls where the agent attempts a close |
| Close Success Rate | Percentage of close attempts that result in accepted next step |
| Objection Recovery Rate | Percentage of objection calls where the user continues or accepts next step |
| Escalation Rate | Percentage of calls escalated to human |
| Unsupported Claim Rate | Percentage of responses containing ungrounded factual claims |
| Average Latency | Average response time after user turn |
| User Frustration Rate | Percentage of calls with negative sentiment, repeated confusion, or user disengagement |

## 17. Agent Conversation Stages

The agent should track one active stage at a time:

- Greeting
- Context confirmation
- Discovery
- Need development
- Knowledge answer
- Objection handling
- Fit summary
- Close
- Escalation
- Wrap-up
- Disqualified

The stage should be updated throughout the call and logged in the decision trace.

## 18. Agent Guardrails

The agent must not:

- Invent pricing, discounts, guarantees, tutor credentials, or policies.
- Pressure the user after clear refusal.
- Continue selling after disqualification.
- Claim to be human.
- Ignore requests for a human.
- Collect payment details unless a secure approved flow exists.
- Make educational outcome guarantees.
- Disparage competitors with unsupported claims.
- Provide legal, medical, or unrelated advice.
- Use manipulative tactics against vulnerable users.

## 19. Failure Modes to Report

The final documentation must include a failure mode report covering:

- Latency problems.
- Barge-in failures.
- Hallucinated policy answers.
- Overly rigid script behavior.
- Premature close attempts.
- Failure to close when buying intent is present.
- Failure to escalate when required.
- Weak objection handling.
- Synthetic prospect bias.
- Poor performance against skeptical humans.
- Incorrect memory carryover.
- Repeated questions.
- Competitive question mishandling.
- Price concession errors.

Each failure mode should include:

- Description
- Example transcript excerpt
- Severity
- Root cause hypothesis
- Mitigation
- Remaining limitation

## 20. User Experience Requirements

### 20.1 Prospect Experience

The prospect should experience the agent as:

- Fast
- Conversational
- Helpful
- Context-aware
- Not robotic
- Not overly pushy
- Honest when it does not know something

### 20.2 Sales Manager Experience

The sales manager should be able to:

- See how the agent is performing.
- Compare versions.
- Review individual calls.
- Understand why the agent made decisions.
- Inspect experiment results.
- Identify failure patterns.
- Approve or reject promoted variants if human approval mode is enabled.

## 21. MVP Acceptance Criteria

The MVP is complete when all of the following are true:

### Voice

- A user can speak to the agent in a live voice channel.
- The agent responds with voice.
- The agent supports natural turn-taking.
- The user can interrupt the agent.

### Sales Flow

- The agent can handle a complete discovery-to-close conversation.
- The agent gathers required information.
- The agent skips already-known information.
- The agent answers KB-grounded questions.
- The agent handles at least three common objections.
- The agent can attempt a close.
- The agent can escalate.

### Memory

- The agent can use prior lead information.
- The agent can remember prior call history.
- Follow-up calls do not restart from zero unless no history exists.

### Observability

- Full transcript is captured.
- Decision trace is captured.
- Outcome is captured.
- Calls are tagged by agent version and experiment variant.
- Dashboard displays core KPIs.

### Recursive Improvement

- Baseline is documented.
- At least two variants are generated.
- Synthetic prospects test baseline and variants.
- KPI comparison is shown.
- One variant is promoted or retired based on evidence.
- Before/after examples are documented.

### Documentation

The final submission includes:

- Failure mode report.
- Recursive improvement description.
- Decision log.
- Research notes.
- Limitations memo.
- Setup and demo instructions.

## 22. Recommended MVP Build Plan

### Phase 1: Core Voice Agent

Build live voice interface, conversation loop, transcript capture, and basic persona.

### Phase 2: Lead Memory and Discovery

Add lead profiles, required fields, dynamic question ordering, and skip-known logic.

### Phase 3: Knowledge Base and Guardrails

Add retrieval for policy, objection, and competitive answers. Add unsupported-answer fallback.

### Phase 4: Decision Logging and Dashboard

Track transcripts, decisions, actions, outcomes, and KPIs in a dashboard.

### Phase 5: Synthetic Prospect Simulator

Build synthetic personas and run test calls against the agent.

### Phase 6: Recursive Improvement Loop

Run baseline, generate price-objection variants, test, compare, and promote or retire one variant.

### Phase 7: Final Hardening

Run human trial calls, document failure modes, refine escalation rules, and prepare demo.

## 23. Decision Log Template

Each major product or technical decision should be recorded as:

- Decision:
- Context:
- Options Considered:
- Chosen Approach:
- Reason:
- Tradeoffs:
- Date:
- Owner:

Example decisions to log:

- STT+TTS versus speech-to-speech.
- Web voice demo versus phone channel.
- Human-approved variant promotion versus auto-promotion.
- Chosen primary KPI.
- Chosen objection improvement dimension.
- Escalation threshold.
- Knowledge-base grounding strategy.

## 24. Research Notes Requirements

Research notes should include:

- Sales methodology references used.
- Objection handling principles.
- Competitive answer constraints.
- Synthetic prospect design rationale.
- Prompt/playbook iteration notes.
- KPI selection rationale.
- Known limitations of synthetic evaluation.

## 25. Limitations Memo Requirements

The limitations memo should clearly state:

- Which lead types were tested.
- Which lead types were not tested.
- Whether real humans tested the agent.
- Whether pricing was real, simulated, or restricted.
- What knowledge-base content was incomplete.
- How synthetic prospects may bias results.
- What would be required for production deployment.
- What compliance, privacy, or sales policy review is still needed.

## 26. Demo Scenario

A strong final demo should show:

- A lead with partial prior information.
- The agent greeting the prospect and confirming known context.
- The agent collecting missing discovery fields.
- The prospect raising a price objection.
- The agent handling the objection using the promoted variant.
- The agent answering a policy or competitor question using the KB.
- The agent summarizing fit.
- The agent attempting a close.
- The dashboard showing transcript, decisions, KPI tags, version, variant, and outcome.
- The recursive improvement dashboard showing baseline versus improved objection-handling performance.

## 27. Success Definition

This project succeeds if it proves three things:

1. The AI agent can conduct a realistic live tutoring sales conversation.
2. The system can be observed and evaluated like a real sales operation.
3. The agent can measurably improve a meaningful sales KPI through a documented recursive improvement loop.

The strongest version does not merely show an obedient AI talking to easy synthetic customers. It shows an agent that can handle hesitation, price pressure, competitive comparisons, partial information, and real-world ambiguity while becoming measurably better over time.
