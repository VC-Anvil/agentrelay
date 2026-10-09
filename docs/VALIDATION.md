# Validation — AgentRelay 0.1.0

Date: 2026-10-09 (Europe/Madrid). Platform: Windows; Python 3.12.14; official MCP Python SDK 1.30.0; desktop in-app Chromium browser. Coordinator integrated backend and frontend specialist packages; review added regressions beyond the authors' tests.

## Automated verification

`python -X utf8 -m unittest discover -s tests -v`: **20 passed**, 30.114 seconds in the final full run. Local raw log: `.agentrelay/verification.log` (ignored, not source).

- 13 domain tests: persistent reopening/export, optimistic revisions, owner protection, Astra configuration restrictions, before/after audit data, help and split workflow, parent/dependency cycles, independent review, explicit isolated demo seeding, and unassigned blocked-task resume.
- 3 HTTP integration tests using real sockets: create/update/conflict/context/export, actionable errors, rejection of cross-origin/host/actor spoofing and path traversal.
- 3 independent integrity tests: two workers competing concurrently for the same revision (exactly one succeeds), preventing new unreviewed children under a closed parent, and profiles without a configurable reasoning setting.
- 1 MCP integration test using an actual official SDK stdio client and server subprocess: initialize/discover → create → claim → request help → second worker delivers help → independent review → parent requeue → resume → checkpoint → submit → reject self-review → independent completion → resource read. No model inference was involved.

`node --check agentrelay/static/app.js`: passed. Companion skill: bundled `skill-creator/scripts/quick_validate.py` reports **Skill is valid!**. Installation of the editable package and CLI help were verified. Source distribution and wheel build succeeded, with static assets and the skill included; distribution checksums are in `dist/SHA256SUMS.txt` after final packaging.

## Browser verification

Against the isolated demo database at `http://127.0.0.1:8788`:

1. Created `AR-0009`, an explicitly labeled QA task, with description, urgent priority, Sol recommendation and two acceptance criteria.
2. Reserved it using the fixture identity `agent:qa-browser`, explicitly recording `prueba-ui-sin-llm` / `none`; these are test declarations, not an agent run.
3. Saved a checkpoint; submitted a summary and `docs/VALIDATION.md` evidence reference.
4. Reloaded the page and confirmed persisted title, priority, recommended profile, execution declaration, review state and evidence URI.
5. Checked both acceptance criteria in the browser and completed the ticket under the UI's separate `human` identity. Observed the ticket in the completed column.
6. Added `QA · Modelo local`, a profile explicitly described as unconnected, with a `none` effort setting.
7. Requested help on `AR-0006`: observed new child `AR-0010`, the dependency and blocked parent state.
8. Switched board/list and filtered by `QA ·`; observed both matching tasks and their distinct states.
9. Exported JSON through the UI and read the actual downloaded file: schema version 0.1.0, 10 tickets, 5 profiles, 20 events, QA ticket `done`.
10. Inspected the actual rendered desktop layout. Screenshot: `docs/preview.jpg`.

## Defects found and corrected

- CSS display rules overrode HTML `hidden`, leaving the loading panel visible. Added an explicit hidden rule and rechecked the rendered layout.
- Active/review tickets had no UI state-transition action. Added it for pausing/requeue/rejection.
- Claim forms prefilled actual settings from recommended profiles. Removed that inference; recommendations remain separate and no runtime launch is implied.
- Raw audit JSON overwhelmed the history. Added readable summaries and expandable original details.
- Profile settings initially excluded models without adjustable reasoning. Added `none`/`default` and verified creation through UI and backend.
- Background refresh rebuilt new-ticket relation selectors without retaining choices. Preserved their selected values.
- Backend review found paused-owner, coordinator-claim and closed-parent scope gaps. Added guards and regression cases.

## Environment attempts preserved

The machine's default Python 3.14 failed while bootstrapping pip in `.venv`. A separate `.runtime` uses the available bundled Python 3.12; no global runtime was modified. Sandbox network isolation prevented real loopback HTTP and stdio subprocess tests; after running the same checks with the required execution permission they passed. These environment failures are not counted as passing tests. Failed environments and caches remain ignored rather than destructively cleaned.

## Limits and continuation

Prepared and technically verified as a local v0.1 application. Human product acceptance and real-model host trials remain separate. The MCP test proves the protocol and shared state, not autonomous task performance. No LLM was launched; no inference quota or cost saving was measured. There is no worker scheduler, hosted deployment, GitHub synchronization, provider telemetry or multi-user authentication. Evidence references require actual reviewer inspection; the application does not certify their contents. Mobile and other operating systems have not been exercised; the added CI matrix has not run on GitHub.

All browser QA was confined to fictional demo data. At validation time the source had not been published. The subsequent publication attempt required storing the CI configuration as `docs/github-actions-tests.yml`: GitHub rejected creation of an active workflow because the publishing credential lacks `workflow` scope. CI is not active; this does not change the application source or the local results above. Continue from `docs/ARCHITECTURE.md` for worker adapters and acceptance policies; configure an actual host using `docs/LOCAL_SETUP.md` when testing an external agent.
