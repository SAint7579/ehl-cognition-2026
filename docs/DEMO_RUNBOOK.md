# Five-minute demo runbook

This runbook demonstrates agentic scientific orchestration, not a claim that
the platform has experimentally engineered a better enzyme. Rehearse once
against the exact deployed frontend, backend, snapshot, and playbook used on
stage.

## Preflight

Complete these checks before the audience arrives:

1. Confirm the frontend and backend deployments are healthy.
2. Open `/api/health` and verify Devin and snapshot configuration.
3. Confirm the default protocol is available in the protocol picker.
4. Confirm the Devin service user has repository and session permissions.
5. Run the deterministic investigation smoke test in the scientific snapshot.
6. Create one private rehearsal investigation and verify artifact harvesting.
7. Keep the rehearsal job and Devin session URL available as a fallback.
8. Close unrelated browser tabs and remove secrets from visible terminals.

Use non-sensitive demonstration inputs only. Do not display service-user keys,
organization secrets, private research data, or backend logs containing
credentials.

## Demonstration objective

Use a stable, rehearsed objective:

> Develop a PET-degrading enzyme that remains useful around 60 °C while
> preserving catalytic function. Produce an inspectable computational
> shortlist and clearly distinguish facts, calculations, predictions,
> inferences, and experimental evidence.

Select the default end-to-end laboratory protocol and submit the investigation.

## Timeline

### 0:00-0:30 — Scientific intent

- Show the objective and protocol selection.
- Explain that the browser sends the request to FastAPI, which creates a Devin
  Cloud session using server-side credentials.
- Submit the investigation.

### 0:30-1:20 — Autonomous plan and execution

- Follow the live progress and worklog rather than opening a raw terminal.
- Point out the plan, active stage, commands, observations, and any recovery.
- Explain that MMseqs2, MAFFT, Foldseek, DSSP, and the Python helpers perform
  the calculations; Devin plans, operates, interprets, and adapts.

### 1:20-2:20 — Inspectable evidence

- Open homolog and conservation outputs.
- Show the catalytic residues and their conservation context.
- Open the interactive 3D structure card. Let it rotate automatically, then
  drag it to demonstrate manual control.
- Select a candidate residue and show its mapped sequence, MSA, and structural
  context.

### 2:20-3:10 — Candidate trade-offs

- Compare activity and stability shortlists without presenting one universal
  score.
- Show the recorded conservation, RSA, secondary structure, catalytic
  distance, score components, and observed homolog substitutions.
- State that these are transparent computational hypotheses, not validated
  improvements.

### 3:10-4:00 — Human steering

Send this follow-up to the existing investigation:

> Exclude mutations within 10 Å of the catalytic site. Re-evaluate affected
> candidates, preserve the previous evidence, and explain every ranking change.

- Show that the same Devin session receives the constraint.
- Show the affected stage returning to active state and the updated result
  version arriving.

### 4:00-4:40 — Provenance and recovery

- Open one evidence/provenance record and identify its tool, version,
  parameters, inputs, and evidence label.
- If the live run contained a genuine recoverable failure, show the condensed
  diagnose/fix/retry sequence.
- Otherwise use the rehearsed run; do not manufacture or trigger a risky live
  failure during the presentation.

### 4:40-5:00 — Close

Use the concise product statement:

> Devin turns a biological engineering objective into an inspectable CPU-native
> investigation. It plans the work, operates real scientific tools, repairs
> failures, responds to constraints, and returns evidence-backed hypotheses for
> human review.

End by reiterating that physical experiments remain the ground truth and require
human approval.

## What success looks like

The audience should be able to answer:

- What objective did the scientist give the system?
- What did Devin decide to do?
- Which real tools produced the evidence?
- Why did a candidate survive the filters?
- Which claims are facts, calculations, predictions, inferences, or experiments?
- How did the workflow change after human steering?

If those answers are visible, the demo succeeds even if a secondary chart or
optional external service is unavailable.

## Recovery matrix

| Symptom | Operator action |
| --- | --- |
| Health endpoint is not configured | Stop; correct backend environment variables without exposing them |
| Protocol list is empty | Use the committed local playbook fallback and state that explicitly |
| New Devin session cannot start | Open the completed rehearsal investigation and explain the recorded session |
| SSE disconnects | Reload; the client should reconnect and recover current job state |
| Artifact is delayed | Continue with available worklog evidence, then refresh the artifact panel |
| 3D rendering fails | Use structure summary and residue tables; do not block the scientific narrative |
| Follow-up remains busy | Explain the active session state and show the rehearsed steered result |

Never swap in unreviewed scientific data, disable evidence labels, expose a
credential, or describe a computational result as experimental to rescue the
demo.

## After the demo

Record the application job ID, Devin session URL, deployed versions, selected
playbook, snapshot ID, and any observed failure. Preserve those identifiers in
the team notes so the demonstration remains reproducible and debuggable.
