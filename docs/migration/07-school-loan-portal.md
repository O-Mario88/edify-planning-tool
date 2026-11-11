# School Loan Application Portal

Built on `feature/edify-go-rn-migration` (2026-11-11). Not merged, not deployed.

## The two journeys

**A school:** opens `/apply/school-loan` from WhatsApp, SMS, email or any
browser → fills in six sections → chooses one lender → submits → gets a
reference and a private status link. No account, no password, no cookie.
The page is plain HTML from the Go gateway (about 15 KB, one small script,
works without JavaScript), in Edify's colours, light and dark.

**Edify:** the application is stored with its outbox task in one
transaction → the delivery worker emails the chosen lender a link (never the
school's details) → the lender opens it with a one-time code, or in the app as
its own staff → records receipt, review, information requests, approval,
decline and disbursement → BTOs follow up, match the school, resend, and
record evidence-backed corrections → the Country Director and RVP oversee →
the dashboard, breakdowns, measures and export report it.

## Who sees what

| Role | Sees | Does |
|---|---|---|
| BTO | every application, in full | follow-ups, take responsibility, match school, resend, corrections, invitations, export |
| Country Director | every application, in full | oversight notes, lenders' receiving addresses and referral switch, export |
| RVP | dashboard and a list without director contact details or fees | oversight notes, export (same redaction) |
| Lender staff (MfiPartnerAdmin, MfiLoanOfficer) | only their lender's applications | record each stage, message Edify |
| Lender via email link | only their lender's applications, after a code | the same |
| Admin, others | nothing | — |

This follows `apps/core/rbac.py` (BTO: portfolio and sensitive views; CD:
also `mfi.manage`; RVP: `businessTransformation.view` only; Admin: "no
implicit governed lending authority"). **Owner to confirm.**

## A lender is offered only when

it is a Loan Partner in the Partner Directory, active; its lender record is
active and under a data-sharing agreement; the Country Director switched
referrals on; and the lender confirmed its receiving address by pressing a
button on the confirmation page (a link scanner cannot confirm it).

## Running it (development)

```
EDIFY_ENV=development EDIFY_ADMIN_DATABASE_URL=postgresql://localhost:5432/edify_gorn_dev platform/deploy/db/apply-roles.sh
EDIFY_ENV=development EDIFY_MIGRATE_DATABASE_URL=postgresql://localhost:5432/edify_gorn_dev schemactl migrate --schema=school_loans --confirm-database=edify_gorn_dev
EDIFY_PUBLIC_BASE_URL=http://localhost:8090 EDIFY_DEV_MAILBOX_DIR=/tmp/edify-mail EDIFY_MAIL_FROM=loans@edify.localhost gateway
```

## Readings the owner should confirm

1. The role table above, especially the RVP's redacted list and Admin's exclusion.
2. Purposes are the brief's ten, stored as stable codes; they are not mapped
   to the existing `bt_loan_purpose` catalogue (its matching entries are
   partly inactive).
3. The religion question's explanation ("only to understand, in total, the
   communities its programmes reach") and that no staff role sees it on a
   record.
4. The privacy notice's retention wording defers to Edify's data-retention
   policy; no period was invented. `EDIFY_LOANS_PRIVACY_CONTACT` sets the
   contact line.
5. A confirmed disbursement is recorded here; the existing BT loan targets
   count the loan ledger (`bt_mfi_loan`). A BTO links the two ("Link the loan
   the lender registered") so nothing is counted twice; nothing is written to
   the ledger from Go.
6. First follow-up is due three days after submission, as in the existing
   intake.

## Not done

- Python analytics on lender processing patterns (the brief says "later").
- Production schema, mail provider and public address (need approval).
- File attachments on follow-ups (a reference is recorded instead; uploads
  need a storage decision).
