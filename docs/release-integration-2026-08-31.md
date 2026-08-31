# Consolidated release — 2026-08-31

This release reconciles the outstanding work against main at
`e2a0b64cdc6229ff4269e8a32370a70c06674e80`. Historical audit reports remain
dated evidence, not a claim that every platform acceptance gate has passed.

## Source decisions

| Source | Resolution |
| --- | --- |
| PR #81, `8dd37843` | Keep the latest plan-derived budgets, grouped activity summaries, role/team scopes, and weekly approval/disbursement/receipt workflow. |
| PR #79, `350935b7` | Its overlapping budget implementation is superseded by #81. Retain dedicated old/new minimum-rate history fields and display that history. Never restore operational-rate fallback for missing minimum rates or the old self-funded settlement path. |
| PR #77, `694ddf81` | Include anonymous document-access fixes, safe policy links, governed-role restrictions, cross-MFI regression coverage, and the second audit report. |
| PR #78, `9431123a` | Include runtime reliability, shared realtime delivery, query aggregation, bounded dashboard caching, database timeout support and operational verification tools. Preserve RVP regional strategy authorship while country master values stay with the permitted country roles. |
| Closed PR #73, `e1ac7927` | Include the chart-rendering performance work and traceability validation. Keep equivalent accessibility fixes already present on main. |
| PR #58, `731ef888` | Preserve the requirement to prevent concurrent migrations. Its old single-instance restriction is superseded by the existing dedicated migration job. |

## Integration corrections

- Count each activity once when dashboard aggregates join several evidence uploads.
- Keep Redis subscription, polling, and cleanup off the ASGI event loop; release subscriptions when a client disconnects during setup.
- Preserve local realtime delivery if a shared-transport read fails after a control message.
- Repair the weekly-request grid's closing tags, keeping the request and supporting plan information inside the same full-width layout.
- Update retired-route and cost-column checks to the unified Budget page and two configured prices. Cost-recipe test fixtures configure minimum rates explicitly.
- Regenerate inventories and the executed journey traceability matrix from the combined source.

## Deployment boundaries

Production is the existing `edify-planning-fra` app
(`8f8682cd-a00a-42d9-b9a6-4fa4b4140bde`), serving `edifyplanning.app`.
Deploy through its existing main-branch integration. Do not replace the live
app specification with a committed example, rotate credentials, change
database bindings, run seed commands, or submit financial transactions as part
of this release.

The pre-deploy job applies two additive migrations: budget minimum-rate
history fields and the weekly-request funding-source field. Existing locked
financial submissions and historical self-funded requests retain their data.
Optional pooled-database configuration remains off unless explicitly enabled
in the live environment. The web image uses the worker configuration from
PR #78, with `WEB_CONCURRENCY` available as a runtime override.

## Verification and rollback

Before merge, require GitHub's full Django, browser, security, and CodeQL
checks, plus approval of the final combined head. After deployment, compare
the live build commit with main and verify readiness, migration completion,
web instances, and scheduler health. Do not describe the rollout as complete
while any of those checks remains unverified.

If the new release cannot become ready or introduces a critical workflow
failure, redeploy the previously healthy application commit. Retain the
additive database columns and financial audit records; do not reverse their
migrations or discard requests created after deployment. Review in-flight
self-funded requests before returning to the old application workflow.
