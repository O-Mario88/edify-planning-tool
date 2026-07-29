# Upload Center, Document Library and Policy Compliance

**Governing principle** — the Upload Center is a control surface, not a second
storage system. Four of its five categories already had an authoritative home,
and it reads those homes rather than copying anything.

---

## 1. What existed, and what was actually missing

Recon first, because the central constraint here was *reuse, don't duplicate*:

| Category | Canonical home | Status |
| --- | --- | --- |
| School import | `schools.SchoolImportBatch` / `SchoolImportRow` | existed |
| SSA import | `schools.SSAImportBatch` / `SSAImportRow` | existed |
| Activity evidence | `evidence.EvidenceRecord` | existed |
| PD certificates | `professional_development.ProfessionalDevelopmentCertificate` | existed |
| Help articles | `help_center.HelpArticle` | existed |
| File security | `evidence.validation.assert_safe_upload` | existed |
| PDF conversion | `evidence.services` (LibreOffice + Pillow) | existed |
| **Policies, manuals, training resources** | — | **missing** |

So exactly one thing was built: `apps/documents`. Everything else is adapted.

## 2. The Upload Center

`/uploads` — one page, five adapters, one normalised row shape (`UploadRow`).
Each adapter reads its own authoritative model and returns a row; the page
sorts, filters and paginates a mixed list without knowing what any of it is.

**No generic upload button.** Evidence without an activity, or a certificate
without a PD record, is an orphan the owning workflow cannot act on — so each
category's upload action is a deep link into the workflow that owns it. Only
policies, manuals and training resources, which have no other home, are
uploaded here.

**Structured imports get a structured preview, never a PDF.** A school roster
is a spreadsheet to be validated row by row; rendering it as a document would
hide the per-row detail the importer exists to show.

Tabs are computed from what a role can actually see. A tab that would always be
empty for a role is not a feature — it is a promise the page cannot keep.

## 3. Five models, not nine

Three of the pieces the specification names separately are one-to-one with a
record that already exists, and a table per concept would buy nothing but joins:

* the **acknowledgement rule** is per-asset configuration → fields on `DocumentAsset`
* the **review decision** is per-version and single-valued → fields on `DocumentVersion`
* the **Help mapping** is one article per asset → a foreign key

`DocumentAudienceRule`, `DocumentAcknowledgement`, `DocumentEngagementSession`
and `DocumentComment` are each genuinely many-per-document and keep their tables.

## 4. The rules that shape the code

**A published version is immutable.** A correction is a new version, so an
acknowledgement always points at exactly the bytes the person agreed to. A
material new version generates fresh pending acknowledgements; the earlier
answers are marked superseded, never rewritten — they are the record of what
that person agreed to at the time.

**An empty audience means nobody.** A document with no audience rule reaches no
one, and that is a critical System Health check — never an accidental broadcast.

**Publication is a gate with a list.** Title, description, owner, audience,
file, effective date and a review decision; mandatory documents additionally
need agreement wording and a stated reason. The list lives in one function so
it cannot quietly shrink.

**A conversion failure never rejects a document.** A manual that will not
convert is still a manual people need: the original is preserved, the viewer
says "Preview Unavailable", and download stays available where permitted.

**Engagement is engagement.** Time accrues only while the viewer reports itself
visible, and a gap beyond the idle threshold starts a new session rather than
being counted — an open tab on a locked laptop is not reading. The figure is
labelled *Active Reading Time* and *Viewer Completion*, never proof of reading.
A reader who used a screen reader, a downloaded copy or a printed copy can
attest to that instead; completion never depends on scrolling to the last page.

**Print records initiation.** The platform cannot see a printer, so the audit
action is `documents.print_initiated` and there is no `documents.printed`.

## 5. The access gate

Middleware, not a template redirect — a redirect only stops the person who
followed a link. Direct URLs, HTMX fragments, DRF endpoints and file routes are
all withheld, in their own idiom: JSON 403 for APIs, `HX-Redirect` for HTMX, a
plain redirect for pages.

A gated person can still read the policy, download or print it where permitted,
answer it, say why they disagree, reach support and log out. A disagreement
restricts access and notifies HR and the CD; nothing is suspended or deleted
automatically, and the person can change their answer at any time. The original
disagreement stays in the audit history either way.

**Cost.** The gate runs on every authenticated request, so the common case is
one `EXISTS` query, memoised per request. The two per-user reads only happen
once a policy configured to block access is actually live.

## 6. Comment privacy

A Program Lead sees *whether* their team answered — chasing that is their job.
They cannot read what anyone wrote: a private comment routed to HR stops being
private the moment a line manager can read it. Reading comment bodies requires
`policies.review_comments`, held by HR, the CD (their own country) and Admin.

## 7. Security

One gate, widened — not a second gate. `assert_safe_upload` gained three
optional parameters so the Document Library can permit presentations and a
larger ceiling while evidence keeps its own limits. Two independent gates
drift, and the weaker one becomes the way in.

Files never leave through a storage URL: `document_path` allow-lists the stored
name and refuses anything resolving outside the store. Malware scanning reuses
the ClamAV path and degrades to `skipped` — never relabelled `clean`. A file the
scanner flags cannot be published.

## 8. No migration, on purpose

There were no policies, manuals or training resources to migrate: no model held
them. Evidence and PD certificates were deliberately *not* migrated either —
they stay in the records that own them.

A migration that manufactured `DocumentAsset` rows for evidence and certificates
would have created exactly the duplicate file system this work exists to avoid.
A migration that invented acknowledgement records would assert that people
agreed to things they never saw. So `document_inventory` reports the estate
instead of transforming it.

## 9. What the platform's own guards caught

Six defects in this work were found by existing tests rather than by me, which
is worth recording because each one is a class of mistake:

1. **`role="tab"` with no panel.** The Upload Center's category links each
   navigate to their own URL and control no panel, so the ARIA role promised a
   screen-reader user a widget that does not exist. They are a `<nav>` of links
   with `aria-current` now.
2. **Hand-built KPI tiles.** The platform requires tiles built through
   `render_metric` so the duplication and denominator guards can see them; a
   hand-rolled tile is invisible to those. Four metrics are now registered.
3. **Four buttons with no explicit `type`.**
4. **Two query budgets, off by one** — the gate's `EXISTS`. Raised by exactly
   one, with the reason recorded in the tests; a fourth query there would mean
   the per-request memo broke.
5. **`country` read off the wrong model.** It lives on `StaffProfile`; reading
   it from `User` returned `""`, which would have made every country-scoped
   audience rule match nobody, silently.
6. **An orphaned `{% endfor %}`** left by template surgery, which 500'd
   `/policy-compliance` for all five roles that can open it. My own tests
   missed it because they exercised the compliance *service* and never rendered
   the page — a page is not covered until something renders it. There is now a
   render test for every page this app owns.

## 10. Known gaps

* **Column mapping UI** for school import (§24) — the existing importer's
  validation, duplicate detection and row-level reporting are reused as they
  are; the Upload Center links to them rather than reimplementing a mapper.
* **Change-request lifecycle** (§24's feature workflow) is not modelled;
  document review is Draft → Under Review → Approved → Published.
* **Break-glass access** to highly restricted documents has no time-limited
  elevation flow; confidentiality classes exist and are enforced by audience.
* **Visual verification** — rendering, permissions, structure and content are
  covered by the test client. Signing in to check the pages visually needs
  credentials, so light/dark and mobile were not eyeballed.
