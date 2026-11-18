# 80 · Edify Global, Phase 0: audit and architecture decisions

Owner instruction, 2026-11-17: *Edify Global — one platform, four countries
(Uganda, Kenya, Rwanda, Ethiopia), same programs, same roles,
country-specific configuration, securely isolated country data.* Phase 0 of
that instruction asks for an audit and the architecture decisions before any
schema change. This document is that Phase 0. The owner approved Phase 1
on §7's recommended defaults on 2026-11-17 ("Yes, start Phase 1"); what has
been built since, on the development copies only, is §8 to §23.

Everything below was measured on 2026-11-17 against the development copy
`edify_gorn_test` and the code on `feature/edify-go-rn-migration`. No
production database was read.

## 1. Where the platform starts from

Edify was built for Uganda. Some of the newer domains already know there is
more than one country; the operational core does not.

### 1.1 What already carries a country (measured)

| Kind | Tables | How |
|---|---|---|
| Free-text country name | `region`, `staff_profile`, `cost_catalogue`, `calendar_block`, `fiscal_year_planning_policy`, `acting_assignment`, `cce_*` engagements, `partner_engagement`, `impact_*`, `hr_*` registers, `document_*`, `pd_*`, `mscs_story` and others | `country = 'Uganda'` (every stored value in the development copy is `Uganda`) |
| A `country_id` string | `monthly_plan`, `monthly_work_plan_budget`, `monthly_budget_submission_snapshot`, `country_annual_budget`, `hr_strategic_priority*`, `hr_milestone_*`, `leadership_escalation` | an identifier with no registry behind it |
| ISO-style `country_code` | `bt_mfi_organization`, `bt_funding_facility`, `bt_policy`, `bt_compliance_requirement` | the loans domain, the most country-ready part of the platform |
| A currency column | `cost_catalogue`, `activity_schedule_cost_line`, `bt_*` loan tables, `hr_compensation`, `pd_*` | `UGX` |

There is **no country registry**. A country is a string, spelled three ways.

### 1.2 What does not carry a country

The operational core has no country of its own: `school`, `activity`,
`cluster`, `ssa_record`, `ssa_score`, `partner`, `partner_assignment`,
`weekly_fund_request`, `advance_request`, `fund_request`, `transport_payment`,
`public_holiday`, `core_plan`, `cluster_activity_attendance`.

A school reaches a country only **through its region**
(`school.region_id → region.country`). Go's country filter
(`internal/schooldirectory/query.go`, `inCountry`) reads it that way and,
for a school with no region, falls back to the country of the school's
holder — and **a school with neither a region nor a holder is placed in
every country**. That is the "country inferred from the address" pattern the
instruction rules out (Part 6.3, Part 13.2), and with a second country it
would show such schools to both. It is the first thing Phase 1 must close.

### 1.3 Uganda assumptions in the code (counted occurrences, excluding tests and migrations)

| Assumption | Django apps | Templates | Go | Next.js | Expo |
|---|---:|---:|---:|---:|---:|
| `UGX` | 725 | 272 | 332 | 48 | 110 |
| `Uganda` | 268 | 57 | 66 | 10 | 14 |
| sub-county | 818 | 222 | 136 | 30 | 44 |
| parish | 99 | 28 | 27 | 6 | 23 |
| district | 4,313 | 793 | 1,357 | 100 | 134 |
| `Africa/Nairobi` | 43 | 0 | 57 | 0 | 0 |
| `Africa/Kampala` | 1 | 0 | 46 | 6 | 3 |

"District" is a word Edify uses for a program unit as well as an
administrative one (District profiles, district targets, cluster rules), so
most of those 6,700 occurrences are not a defect: Part 6 asks for Uganda's
labels to stay as Uganda's presentation. The count is the size of the
surface, not the size of the change.

### 1.4 The foundations, one by one

| Foundation | Today | What the instruction needs |
|---|---|---|
| Geography | Fixed Uganda tables: `region` (4) → `sub_region` (10) → `district` (136) → `county` (0) → `sub_county` (2,562) → `parish` (1,691) → `village` (0); `school` holds a column per level plus the uploaded text of each | A configurable registry of administrative unit types and units per country (Part 6) |
| Financial year | `apps/core/fy.py`: October–September, labelled by the year it ends, hard-coded; Go ports it | Per-country, versioned; Uganda's kept (Part 11.3) |
| Time zone | Django `TIME_ZONE = "Africa/Nairobi"`; Go uses Nairobi in some modules and Kampala in others (same offset, two names) | Per-country IANA zone (Part 5.1) |
| Holidays | `public_holiday (id, name, date)`: no country | Per-country calendars (Part 11.4) |
| Money | Operational amounts are `bigint` whole units with no currency (UGX has no minor unit in use); loans are `numeric(20,2)` with a currency | Original currency and amount on every record; never add currencies (Part 11.1) |
| Language | `LANGUAGE_CODE = "en-us"`; no message catalogs in Next.js or Expo | Catalogs, per-user language (Part 12) |
| School IDs | `school.school_id` is unique platform-wide (`school_school_id_key`); `salesforce_account_id` unique where set | Kept; a national registration number becomes a separate, country-qualified identifier (Part 7.2) |
| Roles | One set (`apps/core/rbac.py` `EdifyRole`): CCEO, Program Lead, CountryDirector, RegionalVicePresident, RegionalProgramLead, ImpactAssessment, Accountant, HumanResources, ProjectCoordinator, PartnerAdmin, PartnerFieldOfficer, BusinessTransformationOfficer, MfiPartnerAdmin, MfiLoanOfficer, ClusterLeader, Admin | Kept exactly; country becomes a separate axis (Part 8.3) |
| Country scope | A country reader's reach is `staff_profile.country` (one country per person) | Explicit, effective-dated memberships, several per person where authorized (Part 8) |
| Acting leadership | `acting_assignment.country` already records the country | Kept; must never leak into another country (Part 8.4) |

## 2. How the multi-country work fits the Go migration

The Go migration is mid-flight on this branch: the app's pages read through
Go, a handful of saves are written by Go behind `EDIFY_GO_SAVES`, and Django
still serves production. Two of its rules decide how country support can be
added:

1. **No existing table is altered** (`platform/README.md`). Django owns the
   production schema; the branch never migrates it.
2. **Go-owned schemas** already exist for new domains (`cluster_leadership`,
   `school_loans`, `field_routes`, `gateway_*`), created through
   `internal/ownedschema`, whose lint refuses anything but creating, altering,
   indexing and granting the schema's own tables.

So the country model can be built **beside** the existing tables, in a
Go-owned schema, without altering a Django table and without touching
production. Uganda's existing behaviour is then the special case "every
existing record belongs to Uganda", which is true today.

## 3. Proposed country model (design, not built)

A Go-owned schema `country_registry` holding:

| Table | Holds |
|---|---|
| `country` | Immutable internal id, stable ISO code (`UG`, `KE`, `RW`, `ET`), name, lifecycle state (Draft, Validated, Ready for Pilot, Active, Suspended, Archived), activation date, data-residency policy reference. No maximum count |
| `country_config_version` | Per country, effective-dated and audited: default and supported languages, currency and precision, IANA time zone, date formats, calendar presentations, financial-year start, changed by, reason, approved by |
| `country_name_alias` | Maps the existing free-text values (`Uganda`) and `country_id` strings to the registry, so the 40-odd tables that already carry a country are read through one key without being rewritten |
| `admin_unit_type` | Per country and config version: canonical type, local label, level, required or optional |
| `admin_unit` | Per country: official name, localised names, official code, parent, validity dates, source, verification status; Uganda's existing `region`/`sub_region`/`district`/`county`/`sub_county`/`parish`/`village` rows are mapped in by id, not copied over them |
| `admin_unit_relationship` | Effective-dated non-tree relationships, cycle- and cross-country-checked |
| `school_country` | `school.id → country`, effective-dated, set explicitly at import or assignment, never inferred from an address |
| `country_membership` | Global user id → country, effective-dated, with the role assignments and scope that apply in that country |
| `country_calendar` | Holidays, school terms and working-day rules per country |

Rows that today have no country (the core tables of §1.2) gain one through
the mapping tables (`school_country`, and the activity's school or cluster),
not through a new column on the Django table. Effective access is the
intersection the instruction sets out (Part 8.3): identity, membership, role,
organisational scope, ownership, acting permissions, sensitive-data limits.

## 4. Data isolation: assessment and recommendation

| Option | For | Against |
|---|---|---|
| A. One shared database, country ownership enforced by Go, defense in depth by Postgres row-level security on the Go-owned tables | One codebase and one deployment; Uganda unchanged; the gateway already runs as least-privilege roles with column grants | RLS cannot be added to Django-owned tables without altering them; until the Django tables are retired, isolation on them is Go's authorization alone |
| B. A database per country behind a data-source configuration | Hard isolation; suits a residency rule | Cross-country oversight needs a separate aggregation path; four sets of migrations and backups; Uganda's database would have to be split from the start |
| C. Schema per country in one database | Middle ground | Same migration and query multiplication as B without B's legal benefit |

**Recommendation:** A now, with the data access written so that a country can
later be served from its own database (B) through configuration if a legal
assessment requires it. RLS policies are fail-closed and apply to the
Go-owned schemas from the first table; the gateway's role never owns the
tables it reads. A residency assessment per country is a precondition for
choosing the production layout, not something this branch can settle.

## 5. Compatibility and risk

| Risk | Where | Mitigation |
|---|---|---|
| Schools with no region and no holder visible in every country | `inCountry` (§1.2) | Phase 1: Go reads country from `school_country`; schools without one are visible to no country until assigned |
| A second country's staff seeing Uganda's schools | Every country-scoped reader resolves `staff_profile.country` | Memberships replace the single string; a missing membership denies |
| Mixed-currency totals | Operational money has no currency column | Every Go read joins the record's country; totals across countries are never summed, only shown per currency or converted with a recorded rate |
| Ethiopian birr has minor units | Operational money is whole-unit `bigint` | Decision 7.4 |
| FY rollover differs by country | `fy.py` and its Go ports | Per-country FY in `country_config_version`; Uganda's October start kept and pinned by the existing boundary tests |
| Holidays apply to everyone | `public_holiday` has no country | `country_calendar`; Uganda's rows mapped to UG |
| Two IANA names for one zone | Go | Every Go module reads the country's configured zone |
| Translations of binding text | Loans | Unreviewed machine translation never used for agreements or notices (Part 12.2) |
| The migration's own scope | ~93 web-only pages still not in Go | Multi-country is built in Go only; Django stays Uganda-only until it is retired |

## 6. Plan

Built only after the decisions in §7 are approved, each phase proved on the
development copies and none applied to production.

| Phase | Builds | Proof |
|---|---|---|
| 1 Global foundation | `country_registry` schema; country config API; memberships; country context resolution in Go; `inCountry` replaced; Uganda seeded as the one Active country with every existing record mapped to UG | The existing goldens unchanged (Uganda behaves exactly as today); isolation tests for a second, Draft country with synthetic data |
| 2 Geography and schools | Admin unit registry with Uganda's tables mapped in; country-aware school import (dry run, duplicates, rejects); School ID kept, national ID separate | Uganda's school counts, IDs and locations reconcile one to one |
| 3 Shared workflows | Country carried through planning, SSA, clusters, partners, budgets, advances, loans, notifications | Goldens per workflow; mixed-currency and wrong-country tests |
| 4 Localisation | Message catalogs in Next.js and Expo; country switcher for multi-country users; country-aware offline store | UI tests per country and language |
| 5 Uganda validation | The whole stack against an isolated copy of Uganda | Reconciliation report (Part 20.4) |
| 6–8 Pilots | Kenya, Rwanda, Ethiopia configured and seeded with approved pilot data | Per-country checklist (Part 21) |
| 9–11 | Global oversight, hardening, release review | Evidence report; no merge or deploy without approval |

The infographic's week counts and performance figures are illustrative;
estimates follow the dependency assessment, and performance claims follow
measurement.

## 7. Decisions needed from the owner

1. **Isolation model** (§4): shared database with Go authorization and RLS on
   Go-owned tables now, per-country databases only if a residency assessment
   requires them?
2. **Existing records**: every record in the existing database is Uganda's,
   mapped to `UG` without rewriting it?
3. **Schools with no region and no holder**: visible to no country until
   assigned (closing the leak in §1.2), rather than to every country?
4. **Money precision**: keep whole-unit amounts for UGX, KES and RWF, and
   store ETB in santim (minor units) with the currency recorded, or keep whole
   birr?
5. **Financial years** for Kenya, Rwanda and Ethiopia: which start month for
   each (Uganda's October–September is kept)?
6. **Country codes**: `UG`, `KE`, `RW`, `ET` as the stable codes, with an
   internal id behind each?
7. **Where Phase 1 starts**: begin the Go `country_registry` schema now, on
   this branch, alongside the remaining migration work?

## 8. Phase 1, first step: the country registry (2026-11-17)

Owner, 2026-11-17: "Yes, start Phase 1", on §7's recommended defaults:
decisions 1 (shared database, Go authorization, RLS on Go-owned tables),
2 (every existing record is Uganda's), 3 (a school with no region and no
holder belongs to no country) and 6 (codes `UG`, `KE`, `RW`, `ET`).
Decisions 4 (ETB precision) and 5 (financial years for KE, RW, ET) stay
open; nothing built so far depends on them.

Built on `feature/edify-go-rn-migration`, applied to `edify_gorn_test`,
`edify_gorn_dev` and `edify_gorn_route` only. No existing table is altered
and no existing row is written.

| Piece | Where |
|---|---|
| Go-owned schema `country_registry` (owner `edify_country_owner`, writer `edify_country_rw`, both NOLOGIN), migration 0001: `country`, `country_config_version`, `country_alias`, `school_country`, `country_membership` | `platform/backend/internal/country/schema`, `platform/deploy/db/country_roles.sql`; applied by `schemactl migrate --schema=country_registry` |
| The legacy seed: UG Active with today's settings (English, UGX with no minor unit, Africa/Kampala, FY from October); KE, RW, ET Draft with no settings; the names `Uganda`/`UG` etc. as aliases; every existing school and account mapped to UG. Idempotent | `internal/country/seed.go`, `countryctl seed-legacy --confirm-database=NAME` (refuses production, a URL the guard refuses, and a database other than the one named) |
| Country resolution: a school's explicit country first, else its region's, else (no region) its holder's; none otherwise. A reader's profile country counts only while the account belongs to that Active country, or has no membership at all (an account the existing application made after the seed) | `internal/country/country.go` (`SchoolIn`, `ReaderCountryIDs`) |
| The School Directory's country bound (`inCountry`) reads the registry; a country reader whose account does not belong to their profile's country is given `NoCountry`, which every module comparing `scope.Country` finds in no record | `internal/schooldirectory/query.go`, `scope.go` |

Proof:

- The lint tests: the migrations load and pass the Go-owned-schema lint,
  which refuses a country column on `school` or `staff_profile`, a foreign
  key into the existing tables and a grant to any other role
  (`internal/country/schema/lint_test.go`).
- Isolation (`internal/integration/country_isolation_test.go`): with a
  synthetic Kenyan school and a school of no country, Uganda holds neither,
  Kenya holds only its own; Uganda's Country Director reaches exactly
  Uganda's schools; an account that belongs to Kenya alone does not read
  Uganda; a Draft country is worked in by nobody, and once Active by its
  members; a Country Director whose Uganda membership is revoked reaches no
  school (not every school).
- Uganda unchanged: the whole integration suite and every golden, 0
  differing; school parity with the existing API, 24 accounts served and 13
  refused, 700 rows, `PARITY OK`.

The other modules that compare `scope.Country` as text are Uganda-correct
and fail closed through `NoCountry`; carrying the registry through them is
Phase 3.

## 9. Phase 1, second step: row-level security and the settings API (2026-11-17)

Owner, 2026-11-17: "Continue Phase 1 with RLS and the config API".

**Row-level security** (`internal/country/schema/migrations/0002_row_security.sql`)
is switched on and forced on all five registry tables, so it binds the owner
role as well as the gateway's. Reading stays open to the registry's roles:
a reader's and a school's country are resolved from these rows before any
country is known, and the resolution falls back to the region or profile
only where a row is absent, so hiding another country's rows would turn
"not yours" into "no country" and fail open. Writing is keyed: a
transaction declares the countries it writes for (`edify.write_countries`)
and whether it may change the countries themselves (`edify.platform_write`),
through `country.WriteFor`; a row of any other country is refused, and a
transaction that declares nothing writes nothing. The legacy seed declares
what it writes, so it runs under the policies too. 0003 lets the gateway read
the migration ledger, as `field_routes` and `school_loans` do.

The schema lint (`internal/ownedschema/lint.go`) was extended for exactly
this: `ALTER TABLE <own table> ENABLE|FORCE ROW LEVEL SECURITY` and
`CREATE POLICY` on an own table, for SELECT, INSERT or UPDATE (never
DELETE or ALL), held by the schema's writer or owner role only, whose
expressions read no table and call only `current_setting`,
`string_to_array` and `coalesce`. Switching it off, `NO FORCE`, `ALTER POLICY`,
a policy on another schema, for another role or for `public` are all refused
(`internal/ownedschema/lint_test.go`).

**The settings API**: `edify.countries.v1.CountryService`
(`platform/proto/edify/countries/v1/countries.proto`, served by
`internal/countryconfig`):

| Call | Who | What |
|---|---|---|
| `ListCountries` | Any signed-in reader | An Admin sees every country; anyone else the Active countries their account belongs to (or, with no membership at all, their profile's). Each with the settings in force today |
| `GetCountryConfig` | Same | Every settings version of a country the reader may see, newest first; a country they may not see answers "not found" |
| `RecordCountryConfig` | Admin only | A new version for a country that is not Active, from today or later and after every version already recorded; the open version ends that day. Languages, ISO currency, minor units 0–3, an IANA time zone, a known date format, calendars (Gregorian always, Ethiopian beside it), FY month 1–12 and a reason are checked first. Written under row-level security declared for that country alone, with the recorder and the reason on the version |

An Active country's settings (Uganda's) are refused outright: they change
only through an approved change, which is not built. Nothing reads the
settings yet, so no existing behaviour can move.

Proof: `internal/countryconfig/validate_test.go` (pilot settings for Kenya
and Ethiopia accepted, 19 malformed ones refused);
`internal/integration/country_config_test.go`: as the gateway's own role,
a write declaring no country is refused, Kenya's settings land only when
declared for Kenya, Uganda's settings and a school placed in Uganda are
refused when declared for Kenya, a country is changed only by a platform
session, and the seed runs; through the API, the Admin sees four countries,
the Country Director and an officer see Uganda alone, a non-Admin cannot
record, Uganda cannot be changed, a past date, a date not after the last
version and a bad zone are refused, and two Kenyan versions follow one
another with the first ending when the second starts. The whole integration
suite and every golden unchanged (0 differing); school parity `PARITY OK`.

Membership management followed in §10.

## 10. Phase 1, third step: country memberships (2026-11-18)

Owner, 2026-11-18: "Yes, memberships".

Three calls join `CountryService` (served by
`internal/countryconfig/membership.go`):

| Call | Who | What |
|---|---|---|
| `ListMemberships` | Any signed-in reader for their own account; an Admin for anyone's | Every membership the account has had, newest first, revoked ones included, each saying whether it gives the account its country today (not revoked, within its dates, the country Active) |
| `GrantMembership` | Admin only, never for their own account | A country for an account from a date (today or later), open-ended or until a later date, with a reason |
| `RevokeMembership` | Admin only, never for their own account | Marks a membership revoked, with who, when and why; the row is kept |

What a grant refuses, before anything is written:

- an account that does not exist or is deleted, a country that does not
  exist, and an Archived country;
- a start in the past, or an end not after the start;
- dates that overlap a membership of the same country that is not revoked;
- a revoked or ended membership of the same country from the same day (the
  registry keeps one row per account, country and start day; a new grant
  starts another day);
- the first membership of an account that has none, when it is not the
  country the account's profile names. Such an account works in its profile's
  country (§8); its first membership replaces that, so granting Kenya alone to
  someone who works in Uganda through their profile would silently take
  Uganda away. The Admin grants Uganda first, then Kenya.

An account's first membership in force is its default; later ones are not.
Changing which is the default is not built (nothing chooses by it yet beyond
ordering).

Every write runs in one transaction declared for the membership's country
alone (`country.WriteFor`), so row-level security refuses a row of any
other country, and holds an advisory lock on the account so two grants for
the same account cannot both pass the checks. Revoking an account's last
membership fails closed: the account then works in no country, and its
profile does not give one back.

Migration 0004 adds `revoke_reason` to `country_membership`, and a check
that a membership is revoked exactly when it has a non-empty reason, so the
table itself refuses a revocation without one. It was applied to
`edify_gorn_test`, `edify_gorn_dev` and `edify_gorn_route` only; no row
existed that it could reject.

A membership is still not access to every record of its country: the
account's role, scope and portfolio decide that, and carrying a role and
scope per country is Phase 3.

Proof: `internal/countryconfig/membership_test.go` (a good grant and 10
malformed ones); `internal/integration/country_membership_test.go`, with an
officer whose memberships are taken away for the test and put back exactly
after: reading is one's own unless an Admin; a Country Director cannot grant
or revoke; an Admin cannot grant themselves or revoke their own; a missing
reason, a written date, an end before the start, a past date, an unknown
country and an unknown account are refused; Kenya before Uganda is refused for
an officer who works in Uganda through their profile; Uganda then lands as
the default and in force, a second overlapping Uganda is refused, a Draft
Kenya lands but is not in force and gives no access; a revocation needs a
reason, keeps its record, cannot be repeated and blocks a re-grant from the
same day; revoking the last membership leaves the officer no country; and the
table refuses a revocation without a reason. The whole integration suite and
every golden unchanged (0 differing); school parity `PARITY OK` (24 accounts
served, 13 refused, 700 rows).

The Admin pages that use these calls are §11.

## 11. Phase 1, fourth step: the Admin pages (2026-11-18)

Owner instruction: *"Continue Phase 1 with the Admin pages."* Three pages in
the Next.js web app, on the calls of §9 and §10. They change nothing the
gateway would not; every write still goes through `CountryService`, which
decides who may.

| Page | Path | What it does |
|---|---|---|
| Countries | `/countries` | Every registered country: code, name, state, the day it became Active, and the settings in force (language, currency, time zone, financial-year start, version). Each name opens its country. |
| Country | `/countries/{code}` | The country's facts and every settings version ever recorded, newest first, with who recorded it, when and why. While the country is Draft, Validated or Ready for pilot, the **Record New Settings** form; for Uganda (Active) the page says its settings change only through an approved change, which is not built. |
| Memberships | `/countries/memberships` | Find an account by name or email (`AccountAdminService.ListAccounts`), then see every membership it ever had (revoked ones with who revoked them and why), **Grant a Country** (country, start, optional end, reason) and **Revoke membership** from the row's one Actions menu, which asks the reason in place. An Admin's own memberships show no actions. |

Only an account working as Admin sees the pages; anyone else is told they
are for Admins. The navigation still mirrors the existing application's
(navigation `rules.json`), so the pages are not in the sidebar yet, as
`/platform-health` is not: they are reached at `/countries`, and from each
other through the Countries / Memberships tabs.

The browser posts to `/country-admin` (same origin only, as Verify
Location's route), which asks the gateway as the signed-in reader. The
forms check what they can before sending (a three-letter currency, language
codes, a default among the languages, a start that is not in the past and is
after the latest version, an end after the start, a reason of at most 500
characters) and show the gateway's own refusal otherwise, such as an
overlapping grant. A save redraws the tables in place; nothing reloads the
page.

Proof: `src/lib/countryAdmin.test.ts` (11 cases: state rules, the tables'
words, membership status, account search rows, and each form check); the web
app's whole unit suite (30 files), `tsc` and `eslint` clean. In the browser,
on `edify_gorn_route` through the gateway on 8090: a CCEO account was told
the pages are for Admins; as Admin, the Countries table, Kenya's page,
recording a Kenya version (shown at once with the Admin's name and reason),
a second same-day version refused, a 30-day Kenya grant for an officer
(shown as not in force: Draft country), an overlapping grant refused, a
revocation refused without a reason and then kept with its reason, the
Admin's own memberships with no actions, and the 375 px phone layout with
tables that scroll whole. The test rows were removed from `edify_gorn_route`
afterwards and the officer's membership put back as it was.

Not built: the pages in the React Native app; a sidebar link (it waits for
the navigation to move to Go); choosing which membership is an account's
default. Role and scope per country followed in §12.

## 12. Phase 3, first step: role and scope per country (2026-11-18)

Owner instruction: *"Start Phase 3 with role and scope per country."* Until
now a membership said only which countries an account works in; the role it
works in, and that role's reach, were the existing profile's everywhere.
This step makes them per country, without changing Uganda.

**Where a country's roles come from.** `country.roles_source` (migration
0005) is `existing_profile` or `registry`:

| Source | Countries | What decides the account's roles and scope there |
|---|---|---|
| `existing_profile` | Uganda | The existing application, exactly as today: `user.roles` and `active_role`, the profile's country, its region and school assignments, acting appointments. Nothing is recorded in the registry and nothing can be assigned there |
| `registry` | Kenya, Rwanda, Ethiopia, and any country added later | Only the roles an Admin assigned under the account's membership of that country (`country_role_assignment`), each with its own scope |

The migration adds the column with `existing_profile` for every country
already registered, so no behaviour moves when it runs, then makes
`registry` the default; the legacy seed then moves the countries that are
not Active (KE, RW, ET; nobody works in them) to `registry`. It never moves
an Active country.

**The role table.** `country_role_assignment`: a membership, its country
and account (a composite foreign key to the membership, so a role cannot be
filed against another country's or another account's membership), the role
(one the existing application defines; never Admin, which is the
platform's own role), its kind of scope (`country`, `regions` or
`portfolio`, from the role as the School Directory reads it), the existing
region ids a regional role covers, and who assigned it, when and why;
revoked ones keep who, when and why. One live assignment of a role per
membership. Row-level security as on the other registry tables: written
only for a country the transaction declares.

**How a request is made in a country.** On every request the gateway reads
the country it is made in: the account's default membership in force of an
Active country, then its others by code; for an account with no membership
at all, the Active country its profile names (`country.Working`). Then
(`auth.Authenticate`):

- that country's roles are the profile's, the account is an Admin, or it
  works in no Active country: nothing changes;
- that country's roles are the registry's: the account holds exactly the
  roles assigned there; the role it asks for counts only when it is one of
  them, the first assigned otherwise; an acting appointment (made in
  Uganda) does not travel; with no role there the request is refused
  ("Your account has no role in Kenya yet. An Admin assigns the roles you
  hold there."), never given the profile's.

The role's scope there (`schooldirectory.resolveScope`, read by every
module that uses the directory's scope, and the HR register's reach): a
country role reaches that country (its name as the existing tables hold
it), a regional role the regions assigned to it there (widened to their
country's regions as `_regional_reach` does today), any other role its
portfolio in the existing tables kept to that country's schools
(`country.SchoolIn`), so an officer moved to Kenya does not keep Uganda's
schools.

**The API**, on `CountryService`:

| Call | Who | What |
|---|---|---|
| `AssignCountryRole` | Admin only, never on their own account | A role under a membership that is not revoked or ended, of a country whose roles come from the registry; a regional role names at least one region of that country, any other names none; a reason. Refused: Uganda (its roles are the profile's), Admin, an unknown role, a role already held there, a region of another country |
| `RevokeCountryRole` | Same | Marks it revoked with who, when and why; the row is kept |
| `ListMemberships` | As before | Each membership now carries its country's roles source and its roles, revoked ones included; an Admin is also given the roles that may be assigned (with their scope and the name people read) and the regions of the account's registry countries |

**The Admin page.** The Memberships page (§11) gains a Roles column
("From the existing profile" for Uganda; the roles held, or "None yet"), an
**Assign role** item in each membership's Actions menu (disabled with the
reason for Uganda, a revoked or an ended membership) that opens the form in
place under the row, and a **Country Roles** table: country, role, scope
in words (Whole country, Regions: their names, Own portfolio), status
(Held; Held, membership not in force; Revoked), who assigned it and why,
who revoked it and why, and **Revoke role** from the row's Actions, which
asks the reason in place. A change redraws the tables in place.

Applied to `edify_gorn_test`, `edify_gorn_dev` and `edify_gorn_route` only
(`schemactl migrate --schema=country_registry`, then `countryctl
seed-legacy`: 3 role sources set). No existing table is altered and no
existing row is written.

Proof:

- Unit: `internal/countryconfig/roles_test.go` (good assignments for an
  officer, a Country Director and a regional lead; 10 malformed ones refused;
  Admin never offered; scope kinds and the names people read);
  `internal/auth/auth_test.go` (Uganda keeps the profile's roles; a role
  assigned in Kenya; a profile role not assigned there falls to the one
  assigned; no role in Kenya is refused; an Admin is the platform's; acting
  appointments do not travel; the regional role's regions);
  `src/lib/countryRoles.test.ts` (5 cases); the web app's whole unit suite
  (31 files, 231 tests), `tsc` and `eslint` clean; the schema lint passes.
- Integration (`internal/integration/country_roles_test.go`), with an
  officer whose memberships are taken away and put back exactly after: an
  Admin is offered every role but Admin and Kenya's one region; a Country
  Director cannot assign; an Admin cannot assign on their own account;
  Uganda, Admin, a regional role with no region, a Ugandan region for Kenya
  and an unknown membership are refused; CCEO and a regional lead land in
  Kenya with their scope and who assigned them; the same role twice is
  refused; while the officer works in Uganda nothing assigned in Kenya
  applies; with Kenya Active and Uganda revoked the officer's session holds
  exactly CCEO and the regional lead, the portfolio holds none of Uganda's
  schools and the regional lead reaches Kenya's region; a revocation needs a
  reason, keeps its record and cannot be repeated; with no role left the
  officer is refused; the table refuses a role whose country is not its
  membership's, and row-level security refuses a Kenyan role written in a
  transaction declared for Uganda.
- Uganda unchanged: the whole integration suite and every golden, 0
  differing; school parity with the existing API, 24 accounts served and 13
  refused, 700 rows, `PARITY OK`.
- In the browser, on `edify_gorn_route` through the gateway on 8090, as
  Admin: Kenya granted to an officer; the Roles column; Assign role from the
  Kenya row (a regional role says Kenya has no regions yet and is stopped
  before sending); CCEO assigned and shown at once in both tables as held
  while the membership is not in force (Kenya is Draft); a revocation
  refused without a reason, then kept with its reason; Uganda's Assign role
  disabled with why; the 375 px layout with tables that scroll whole. The
  test rows were removed afterwards and the officer's membership put back as
  it was.

Not built yet: assigning roles in the React Native app; per-country
supervision and team structure (a Programme Lead's team still comes from the
existing supervisor table); moving Uganda to the registry (it waits for the
existing application to stop owning roles); the rest of Phase 3, carrying
the country through planning, SSA, clusters, partners, budgets, advances,
loans and notifications. Planning followed in §13.

## 13. Phase 3, second step: the country through planning (2026-11-18)

Owner instruction: *"Continue Phase 3 with the country through planning."*
Planning's records, people and settings now follow the country a request is
made in (§12), read through the registry instead of comparing a country's
name as text. No table is added or changed in this step and no row is
written; it is Go code only.

**Which work belongs to a country** (`country.ActivityIn`). The existing
rule (`activity_country_q`) placed an activity by its school's region, its
cluster's region or district, or its responsible person's profile, and put
work at a school with no region and no country-bound holder in *every*
country. The registry rule places the school by `country.SchoolIn` (its
recorded country, else its region's, else its holder's), keeps the cluster
and responsible-person routes, and puts a school of no country in none
(owner decision 3, §8). Every page that used the shared clause now reads it
with the scope's country id (`Scope.CountryID`, filled beside
`Scope.Country`): My Plan's school activity list, the Calendar, Team Plans,
the IA pages (reach, samples, analytics), the IA to-dos, Reports and Batch
Payments. A reader bounded to no country (`NoCountry`) still finds nothing.

**People in a country** (`country.RosterIn`, `HoldsRoleIn`, `BelongsTo`).
The Planning Monitor's roster, the Calendar's country teams and the
Country Director's approval team:

| Country's roles | Who is on the roster |
|---|---|
| The existing profile's (Uganda) | Today's rule unchanged (the role on the account, the profile naming the country or none), kept to accounts that belong to the country, so someone who now belongs only to Kenya leaves Uganda's roster |
| The registry's (Kenya, Rwanda, Ethiopia) | The people holding the role there under a membership in force, with the roles they hold there |

**Projects** (Work Plan's project list): a project is a country's when one
of its schools is (`SchoolIn`) or its manager's profile names the country.

**Planning settings by country** (`country.SettingsName`). The existing
tables key planning settings by the country's name ("Uganda"). Uganda,
and any request made in no Active country, reads exactly the rows it reads
today; a country whose roles come from the registry reads its own rows by
its own name, and finds none until they are recorded:

| Setting | Where it is read |
|---|---|
| The cost catalogue (`cost_catalogue.country`) | The Planning page's costing strip; My Plan's group-training meal rate |
| The planning calendar (`fiscal_year_planning_policy.country`): which later years are open, and whether a follow-up visit needs a prior training | Work Plan, the Planning Monitor, FY Planning, the planning horizon shared by the Planning page, Cluster schools, Core Schools, Oversight Portfolio, Project Monitoring and Planning Oversight, and scheduling a follow-up visit |
| The annual budget approval (`country_annual_budget.country_id`) | Work Plan |

So a Kenyan planner sees no catalogue (costing is blocked, as for a country
with none) and no later year open, rather than Uganda's.

Proof:

- Unit: `internal/country/planning_test.go` (settings keys for no country,
  Uganda and Kenya; the three rosters; the activity clause reads the
  registry and no longer places work everywhere); every backend unit test
  and `go vet ./...` pass.
- Integration (`internal/integration/country_planning_test.go`), with Kenya
  Active, an Impact Assessment officer and a CCEO who belong to Kenya alone
  (their memberships taken away and put back exactly after), a Kenyan
  school and a Ugandan school with no region and no holder, and work at
  each: Team Plans through the gateway shows Kenya's IA only Kenya's work and
  Uganda's IA only Uganda's (the existing rule would have shown Kenya the
  Ugandan school's work too); the activity clause agrees; Kenya's roster is
  the Kenyan CCEO alone, and Uganda's no longer holds them though their
  profile still says Uganda; Kenya's settings are keyed "Kenya" and it has
  no catalogue and no open planning year.
- Uganda unchanged: the whole integration suite and every golden, 0
  differing; school parity with the existing API, 24 accounts served and 13
  refused, 700 rows, `PARITY OK`.

Not in this step:

- **The financial year per country.** Every planning page still rolls the
  year over on 1 October, Uganda's. The registry holds each country's
  financial-year month (§9), but Kenya's, Rwanda's and Ethiopia's are owner
  decision 5, still open, and about 80 Go files compute the year; it needs
  one shared, country-aware year before any page changes.
- **Holidays and organisation events**: `public_holiday` has no country, and
  the calendar blocks are read by the profile's country; a country calendar
  (§3, `country_calendar`) comes first.
- **A project with no schools and no manager** still shows in every country,
  as today: projects have no country of their own yet.
- **The targets engine** (`internal/allocations`) keeps its own copy of the
  existing activity rule; it moves with targets.
- Writes: scheduling already stays inside the country, because it requires
  the school in the scheduler's own portfolio, which §12 keeps to the
  country's schools.

## 14. Phase 3, third step: the country through SSA (2026-11-18)

Owner instruction: *"Continue Phase 3 with the country through SSA."*
SSA records belong to schools, so an SSA record's country is its school's
in the registry (`country.SchoolIn`). Go only reads SSA; recording,
importing and confirming scores stay in the existing application. No table
is added or changed and no row is written.

Most SSA readers already reach records through the School Directory's
scope (a portfolio, or a country read through the registry since §8): My
Plan, the Planning page, Core Schools, the Programme Rollout, the
dashboards, My Targets and the IA outcome pages. The ones that compared a
country's name as text now read the registry:

| Reader | Before | Now |
|---|---|---|
| The SSA verification queue (`/ssa/verification/`) for a country reader | The school's region's country name, or a school with no region and no country-bound holder in every country | The school's registry country (`SchoolIn`) |
| Which records a Country Director confirms (those Impact Assessment collected) | Collected by anyone holding Impact Assessment anywhere | In a country whose roles come from the registry, by the people assigned Impact Assessment there (a revoked assignment still marks what they collected); Uganda's rule unchanged |
| The SSA change rules that apply to a school (Core Oversight, Cluster Oversight) | The school's region's country name | The school's registry country's name (`country.SchoolCountryName`) |
| The IA dashboard's SSA operations: unmatched SSA rows, failed uploads, districts below the SSA target | The uploader's profile country; the suggested school's region; the regions named by the country | The country's people (`country.UsersIn`: in Uganda, today's rule kept to its members; elsewhere, its members), the suggested school's registry country, the country's regions (`country.RegionsIn`) |
| The IA geography (district groups and region links) | Regions named by the country | `country.RegionsIn` |

Proof: `internal/integration/country_ssa_test.go`, with Kenya Active, an
Impact Assessment officer and a CCEO who work in Kenya alone, a Kenyan
region, a Kenyan school and a Ugandan school with no region and no holder,
and a pending SSA at each: Kenya's IA sees only Kenya's record in the
verification queue and Uganda's IA only Uganda's (the existing rule would
have shown Kenya the Ugandan record too); the schools' rule countries are
Kenya and Uganda; Kenya's regions and people are its own and Uganda's no
longer include the officer who left. The shared test setup
(`country_kenyans_test.go`) now fails the test outright when its cleanup
cannot run, so a role left behind can never keep memberships from being
put back. The whole integration suite and every golden unchanged (0
differing); school parity `PARITY OK` (24 accounts served, 13 refused, 700
rows).

Not in this step: SSA writes (in the existing application); a
country-specific SSA framework (the interventions and score bands are the
existing rules; per-country change rules already exist as
`activity_intervention_mapping.country` and now apply by the registry
country); the IA pages outside SSA (stories, reports, verification reach),
which keep their text rule until they are carried.

## 15. The regional roles work across every country (2026-11-18)

Owner, 2026-11-18: *"All the regional roles like RVP, HR, RegionalProgram
Leads, Business Transformation Officer, should have access to all the
countries."*

The four regional roles are `RegionalVicePresident`, `HumanResources` (the
Regional HR Director), `RegionalProgramLead` and
`BusinessTransformationOfficer` (`country.IsRegional`). Like Admin they are
the platform's, not one country's:

| Where | Rule |
|---|---|
| Holding the role (`auth.rolesInCountry`) | A regional role comes from the account's profile in the existing application, as today. In a country whose roles come from the registry, the account keeps its regional roles beside the roles assigned there, and is not refused there for holding only a regional role |
| Assigning roles per country (`AssignCountryRole`, the Memberships page) | A regional role is refused ("… works across every country: it comes from the account's profile, not from one country") and never offered; the Assign role form says so. A regional role assigned earlier is never treated as held in that country (`HeldInCountry`) |
| Reach (`schooldirectory.resolveScope`) | The Regional Vice President and Regional Programme Lead reach every region of every country (the existing rule reached only the countries their assigned regions were in); the Business Transformation Officer, a country-wide role, is bounded by no country, as the Admin is |
| The People register (`hrregister`, and the Debrief dashboard that reads it) | A regional role, the Regional HR Director among them, reads the People records of every registered country (every name the registry gives a country); a record that names no registered country stays the Admin's. The existing rule read the countries the director's geography named; that branch is removed |
| The country list (`ListCountries`) | A reader working in a regional role sees every Active country |

Every page that reads the directory's scope follows: the BT pages and
to-dos, the RVP and RPL dashboards and oversight pages, and the planning
and SSA readers of §13 and §14.

For Uganda the data does not change what these roles see while Uganda is
the only Active country with schools, regions and people: every region is
Uganda's, every school is mapped to Uganda and every People record names
Uganda. It changes what they would see once another country has records,
which is the owner's intent.

A first version gave the Regional HR Director the Admin's reach (every
People record, live or not, of any country or none); the Debrief dashboard's
golden caught it (one answer differing for the HR Director), and the reach
is now every country's records, which is what the owner asked for.

Proof: `internal/auth/auth_test.go` (a regional role kept beside Kenya's
assigned roles; an account holding only a regional role is not refused in
Kenya; a regional role is never held through one country);
`internal/countryconfig/roles_test.go` (each regional role refused per
country and not offered); `internal/integration/country_roles_test.go`
(each regional role refused through the API; a Regional Programme Lead
working in Kenya reaches both Kenya's and Uganda's regions and no country
bound); the whole integration suite and every golden, and school parity.

Consequences to note: per-country region scope (`scope_type = regions`)
now has no role that uses it, since both roles that cover regions are
regional; it stays in the schema for a country-level regional role should
one be defined.

## 16. Phase 3, fourth step: the country through clusters (2026-11-18)

Owner instruction: *"Continue Phase 3 with the country through clusters."*
A cluster has no country column; it is placed by its region, or its
district's region (`country.ClusterIn`), whose country name is read
through the registry's names. No table is added or changed and no row of
the existing application is written.

| Where | Before | Now |
|---|---|---|
| Cluster Oversight and the cluster pages (`cluster_queryset` for a country reader) | The cluster's region or district region named the country's text | `country.ClusterIn` with the scope's registry id |
| Whether a country reader may open a cluster's schools | The same, as a text comparison | The same registry rule |
| The Cluster Leader portal: which clusters a Programme Lead manages leaders for, and whose leaders they may assign, end or replace | Every cluster in the platform | The clusters of the country the Programme Lead works in; none while they work in no Active country. An Admin still manages every cluster; a CCEO their own, as before |
| The cluster support requests left unassigned (a Programme Lead's team queue) | Every unassigned request | Those at schools of the Programme Lead's country (`country.SchoolIn`) |

So a Programme Lead working in Kenya can no longer assign, end or replace
the leaders of a Ugandan cluster, and Uganda's cannot touch Kenya's. For
Uganda's data nothing moves: every cluster has a Ugandan region.

Proof: `internal/clusterlead/service_test.go` (a Programme Lead manages
their own country's clusters, not another country's, and none while
working in no Active country; the Admin manages every country's);
`internal/integration/country_clusters_test.go`, with Kenya Active, a
Kenyan region, district and cluster, and an officer who is Programme Lead
in Kenya alone: the cluster rule places the Kenyan cluster in Kenya only;
through the gateway, Kenya's Programme Lead manages Kenya's cluster alone
and is refused a Ugandan cluster's leaders, Uganda's Programme Lead keeps
the Ugandan clusters and is refused Kenya's, and the Admin manages both;
the whole integration suite and every golden, and school parity.

Not in this step: the training summary (cluster trainings, coverage and the
per-country training ceilings) keeps its own country from the reader's
profile; it moves with trainings. Creating or editing clusters is the
existing application's.

## 17. Phase 3, fifth step: the country through partners (2026-11-18)

Owner instruction: *"Continue Phase 3 with the country through partners."*
The existing `partner` table has no country. A partner's country is now a
row in the registry, never a new column on the existing table, as a
school's is.

**Migration 0006** (`country_registry.partner_country`): partner id,
country, effective dates, source (`legacy_uganda`, `import`,
`assignment`), who recorded it and when. A partner may work in more than
one country, each with its own dates. Row-level security as on the other
registry tables: read by the registry's roles, written only for a country
the transaction declares. Applied to `edify_gorn_test`, `edify_gorn_dev`
and `edify_gorn_route` only; the legacy seed (`countryctl seed-legacy`)
recorded every existing partner in Uganda (6, 8 and 6 partners).

**Which country a partner works in** (`country.PartnerIn`): its recorded
countries in force. A partner with no recorded country at all, one the
existing application creates after the seed, is read as Uganda's (the
country whose roles are the existing profile's), since that application
serves Uganda alone; a partner whose recorded countries have all ended
works in none.

**Where it is enforced.** Most partner reads in Go already follow the work
(Partner Oversight reads the reader's own team and schools; the partner
workspace, assigned work and payments are the partner's own records), so
they were country-bound through the school scope. The country-wide one was
partner team management (`teams.PartnerService`): the Country Director,
Impact Assessment and the Accountant could read and change *any* partner's
team, add members and create their logins. Now:

| Reader | Partner teams they read and change |
|---|---|
| Admin, and the regional roles (§15) | Every partner |
| Country Director, Impact Assessment, Accountant | The partners of the country they work in; none while they work in no Active country |
| A partner's own Partner Admin or login | Their own organisation, as before |

So Kenya's staff cannot add members to, or create logins for, a Ugandan
partner, nor Uganda's for a Kenyan one.

Proof: `internal/integration/country_partners_test.go`, with Kenya Active,
a Kenyan partner, an unrecorded partner and an Impact Assessment officer
who works in Kenya alone: the rule places the Kenyan partner in Kenya only
and the unrecorded one in Uganda; through the gateway, Kenya's IA reads
Kenya's partner team and is refused a Ugandan or unrecorded partner's,
Uganda's IA reads Uganda's and the unrecorded partner's and is refused
Kenya's, the Admin reads both; Kenya's IA adding a member to a Ugandan
partner is refused and nothing is written. The schema lint passes; the
whole integration suite and every golden, and school parity.

Not in this step: recording a partner in a country from a page (it is
`import` or `assignment` data, set where partners are onboarded, which is
the existing application's); handing school work to a partner (the
existing application's), whose country check comes with it.

## 18. Phase 3, sixth step: the country through budgets (2026-11-18)

Owner instruction: *"Continue Phase 3 with the country through budgets."*
No table is added or changed and no row of the existing application is
written; it is Go code only.

**The country's Budget** (`/budget`, the country view the Country Director,
Accountant, Impact Assessment, Regional Vice President and Admin read). It
read every planned cost line and every advance in the platform. It now
reads only the country the request is made in:

| Figure | Kept to the country by |
|---|---|
| The planned cost lines (the ledger, the groups, the grand total) | `country.ActivityIn` on each line's activity |
| Finance Health (the year's advance pipeline) | The same, on each advance's activity |
| The month's live request (`_recompute_if_live`) and its reconciliation | The same, on the month's lines and advances |
| The month's budget row and the earlier month still pending | The country's own row (`monthly_work_plan_budget.country_id`, keyed as `country.SettingsName` names it: "Uganda" for Uganda) |

Money is never summed across countries. The Admin and the regional roles,
who reach every country (§15), read the Budget of the country they work in;
a view of every country side by side, each in its own currency, waits for
the country switcher (Phase 4). With no country to keep it to (a caller
working in no Active country), the existing page's rule is kept: a platform
whose People name several countries is handed on.

**Currency.** The page wrote every amount as UGX. It now writes the request's
country's currency, from its settings in force (`country.CurrencyOf`), in
the same form (`KES 12,345`, `KES 1.2M`), and the chart's labels follow;
UGX wherever no currency is recorded, so Uganda's page is unchanged.
Amounts stay whole units: ETB's precision is still owner decision 4.

**Prices.** The published rate card that costs work when it is scheduled
(`pricing.ReadCard`) and the Cost Settings page read the request's country's
card (`auth.SettingsName`: Uganda's card wherever the caller works in a
country whose roles are the existing profile's, or there is no caller). A
country with no published card has none, so its work is not costed on
Uganda's rates in Uganda's currency.

Proof: `internal/budgetpage/currency_test.go` (UGX unchanged; KES, RWF and
ETB in both forms); `internal/integration/country_budgets_test.go`, with
Kenya Active and keeping its money in KES, a Kenyan school with one planned
cost line of 12,345 and an Impact Assessment officer who works in Kenya
alone: Kenya's Budget totals exactly that line, as `KES 12,345`, and shows
no UGX; Kenya's currency is KES and it has no rate card while Uganda's are
read as today. Uganda unchanged: the Budget page's own golden (28 answers
over 9 accounts, the country's Budget among them), the Cost Settings golden
(15 answers), and the four pricing oracles (264 activities priced, 239
saves checked, 7 shared days, 276 stored activities), all 0 differing; the
whole integration suite and every golden; school parity `PARITY OK`.

Not in this step: the other pages that write UGX (fund approvals,
disbursements, partner payments, the cost settings tables) move with
advances and payments; ETB minor units (decision 4); a cross-country view.

## 19. Phase 3, seventh step: the country through advances (2026-11-18)

Owner instruction: *"Advances"* (Phase 3's next step). No table is added
or changed and no row of the existing application is written; Go code only.

The money pages of the advance workflow read every country's money and
wrote it all as UGX. They now read the country the request is made in, in
its currency. The Admin and the regional roles read the country they work
in, so money is never summed across countries (as the Budget, §18).

| Page | Kept to the country |
|---|---|
| Fund Disbursement Dashboard (`/disbursements`, Accountant, Admin) | The month's monthly fund plans and weekly advances (by whose they are, `country.AccountIn`), the partner work awaiting payment and the reimbursement claims (by their activity, `country.ActivityRowIn`), the month's figures (released today, disbursed, allocation) and the recent activity |
| Weekly Fund Requests (a country reader's view) | The requests (`AccountIn` on whose they are), the activities and the cost lines (`ActivityRowIn`) |
| Partner Payment Queue | The PL-confirmed invoices of the country's partners (`country.PartnerIn`) and the verified partner work (`ActivityRowIn`) |
| Batch Payments Center | As before for a country reader, and now also the Admin's and regional roles' working country |
| Fund Approvals | Already the approver's team (§13); its money is now in the country's currency |

**Work no country holds** (`country.ActivityHeldIn`, used by these pages and
by the Budget of §18). The existing application reads its money pages
across the whole platform, not by country, so they show work that the
activity rule (`ActivityIn`) places in no country at all: no school, no
cluster, and a responsible person whose profile names no country (a
cluster-wide partner activity, for one). Such work is held by Uganda, as
everything that application holds is Uganda's; work placed in a country
stays that country's. The Partner Payments golden caught the gap (a
cluster-wide partner activity missing from Uganda's queue) before the rule
was added. Planning and SSA readers keep `ActivityIn`, as the existing
`activity_country_q` leaves such work out.

**Who an account works for** (`country.AccountIn`): a membership of the
country in force, or, for an account the existing application made after
the registry was seeded (no membership at all), Uganda, as everything
that application holds is Uganda's.

**Currency.** The country's currency is now read with the country the
request is made in (`country.Work.Currency`, from its settings in force),
and every amount on these pages, their tables' column labels, the shared
ledgers (`budgetpage.CostLineLedger`, `WeeklyRequestLedger`) and the
budget-mix legend (`fundworkspace.Mix`) are written in it
(`budgetpage.In`, `CompactIn`, `CurrencyCode`, `CurrencyFrom`): UGX
wherever no currency is recorded, so Uganda's pages are unchanged.

Proof: `internal/integration/country_advances_test.go`, with Kenya Active
and keeping its money in KES, a Kenyan and a Ugandan monthly fund plan
awaiting disbursement (77,777 and 88,888), and an officer who is
Accountant in Kenya alone: Kenya's dashboard holds Kenya's plan alone, as
`KES 78K`, and no UGX; Uganda's Accountant sees Uganda's alone, as
`UGX 89K`, and no KES. Uganda unchanged: the Disbursement, Fund Approvals,
Weekly Request, Batch Payments and Partner Payments goldens and the whole
integration suite, 0 differing; school parity `PARITY OK`.

Not in this step: the cost settings tables' "UGX" column labels (the rate
card's own currency follows when a country's card is recorded); loans,
which are their own step.

## 20. Phase 3, eighth step: the country through loans (2026-11-18)

Chosen next by me under the owner's standing instruction of 2026-11-18
("I will leave you to make the next decision for the next task"). No table
is added or changed and no row is written; Go code only.

School loans are Go's own (`school_loans` schema, `internal/loans`). The
existing permission model gave the Business Transformation Officer, the
Country Director and the RVP every application. The BTO and the RVP are
regional roles and keep every country (§15); the Country Director is a
country role, so their reach is now their country's:

| Call | For the Country Director |
|---|---|
| Applications list, export, dashboard totals, breakdowns and measures (one `Filter`) | Applications at a school of their country (`country.SchoolHeldIn`) |
| One application (open, follow up, oversight note, tracking, match, resend, correction, link a registered loan) | Refused as "No such application." when it is another country's |
| A school's loan history, a school invitation | Refused as "No such school." when the school is another country's |
| Lender receiving addresses (list, save, send confirmation) | The lenders whose partner organisation works in their country (`country.PartnerIn`); another country's refused as "No such lender." |

**Unplaced records** (`country.SchoolHeldIn`): an application not yet
matched to a school, or at a school the registry places in no country, is
Uganda's, as everything the existing application holds is. A lender whose
partner has no recorded country is Uganda's (§17).

**Currency.** Loan amounts stay in the schema's UGX columns
(`requested_amount_ugx` and the rest). Another country's applications
cannot be made yet: the public form resolves the school's district,
sub-county and parish against Uganda's places, and other countries' places
come with Phase 2's geography. Recording an application's currency comes
with that.

Proof: `internal/integration/country_loans_test.go`, with Kenya Active, a
lender recorded in Kenya, another unrecorded (so Uganda's), an application
submitted through the public form and not yet matched (so Uganda's), and
an officer who is Country Director in Kenya alone: Kenya's Country Director
does not list the application, is refused it by its id, manages only the
Kenyan lender's address and is refused the Ugandan lender's confirmation;
Uganda's Country Director lists and opens the application and manages only
the Ugandan lender. The loan suites (portal, follow-ups, sharing,
statements, existing terms), the whole integration suite and every golden
unchanged; school parity `PARITY OK`.

## 21. Phase 3, ninth step: the country through notifications and messages (2026-11-18)

Chosen next by me under the owner's standing instruction. No table is added
or changed; Go code only.

The Notification Centre (`internal/notificationcenter`) reads each
account's own notifications, so it is already per person and needs no
country rule. Messages carry a record (a school, a cluster, an activity,
a fund request…); the inbox shows a conversation only to readers who may
open its record (`messaging.gate`). Two of its rules ignored the country:

| Rule | Before | Now |
|---|---|---|
| A country reader opening a conversation's school | Any school at all | A school of their country (`country.SchoolHeldIn`); an unbounded reader (Admin, a regional role) any school |
| A country reader opening a conversation's activity | Any activity at all | An activity of their country (`country.ActivityHeldIn`) |
| Field staff opening a school nobody holds "in their country" | The country their profile names | The country they work in, where its roles come from the registry |

Records the registry places in no country are Uganda's, as the existing
application, which served Uganda alone, let every country reader open them.
Clusters already followed the cluster rule of §16.

Proof: `internal/integration/country_messaging_test.go`, with Kenya Active,
a Kenyan school and an Impact Assessment officer who works in Kenya alone:
Kenya's officer is shown the conversation about the Kenyan school and not
one about a Ugandan school, and Uganda's officer the reverse. The messaging
integration tests, the whole integration suite and every golden unchanged;
school parity `PARITY OK`. (The inbox's own proof against the existing
page writes, since the existing page marks conversations read, so it is run
only on a shadow copy and was not run for this step.)

## 22. Phase 3, tenth step: the country through trainings (2026-11-18)

Chosen next by me under the owner's standing instruction. Go code only.

The Training Summary (Planning Oversight → Training Summary, with its
Country Ceilings, staff and schools tabs) took its country from the
reader's profile text. It now reads a **place** (`trainingsummary.place`):

| | A country whose roles are the existing profile's (Uganda) | A country whose roles come from the registry |
|---|---|---|
| Country name (the Country Ceilings' key, `training_country_ceiling.country`) | The profile's country, else the platform's default, as today | The country the reader works in |
| The country's officers (the CCEOs and Programme Leads it lists) | The profile rule as today | The people holding CCEO or Programme Lead there (`country.HoldsRoleIn`), with the roles they hold there |
| Whose plans count (`_country_identities`) and the Schools tab's staff | The profile rule as today | The accounts that work in the country (`country.AccountIn`) |

Proof: `internal/integration/country_trainings_test.go`, with Kenya Active
and an Impact Assessment officer and a CCEO who work in Kenya alone:
Kenya's Training Summary offers only the Programme Lead of Kenya's CCEO,
and Uganda's offers the Leads of Uganda's officers. The Training Summary's
own tests, the whole integration suite and every golden unchanged; school
parity `PARITY OK`.

With this step, Phase 3's areas named in §6 have been carried through
(planning, SSA, clusters, partners, budgets, advances, loans,
notifications, trainings), except the financial year per country, which
waits on owner decision 5.

## 23. Country isolation in the database (2026-11-18)

Owner, 2026-11-18: *"enforce country isolation in both Go and the database.
PostgreSQL supports Row-Level Security, which can provide an additional
layer of protection beyond ordinary application permissions. This should be
implemented and tested carefully, including how database connection pooling
handles country context."*

**The country on every connection** (`internal/countryctx`). The gateway's
pool is shared by every request, so each connection carries the session
setting `edify.read_countries`, written when the connection is taken out of
the pool (pgx `PrepareConn`) whenever the request wants a value other than
the one the connection last carried:

| Request | `edify.read_countries` |
|---|---|
| A signed-in caller working in a country | That country's code (`UG`, `KE`) |
| The Admin, a regional role (§15) | `*`: every country |
| A signed-in caller working in no Active country | Empty: no guarded row is theirs |
| No signed-in caller: the platform's own work (the public loan form, school and lender token pages, workers, start-up checks) | `*` |

A connection therefore never keeps a previous request's country: the value
is checked on every checkout and rewritten when it differs (a cached value
per connection saves the round trip when consecutive requests share a
country). If writing it fails, the pool discards the connection. Both
`cmd/gateway` and the integration harness configure their pools this way.
Transactions that declare the countries they write (`country.WriteFor`,
§9) are unaffected: those settings are transaction-local.

**The first guarded table** (school loans migration 0008).
`school_loans.application` gains `country_code` (every application already
recorded is Uganda's, owner decision 2), written when an application is
submitted and again when it is matched to a school (the school's registry
country, else Uganda's: `country.SchoolHeldIn`). Row-level security is on
and forced: a row is read, inserted or updated only when
`edify.read_countries` is `*` or names its country; another country's row
is invisible, cannot be changed and cannot be filed. Only the gateway
reads the `school_loans` schema, so no other service is affected. The
Go checks of §20 stay in front of it.

Proof: `internal/countryctx/countryctx_test.go` (the value for each kind of
request); `internal/integration/country_rls_test.go`, through a pool of one
connection as the gateway's own role, so every request reuses the same
session: a Ugandan application is seen by a reader working in Uganda, the
Admin and the platform's own work, and by no reader working in Kenya or in
no country, with the requests alternating twice over on the connection; a
reader working in Kenya changes no Ugandan application and is refused
filing one as Uganda's. The loan suites (the public form writes as the
platform's own work), the whole integration suite and every golden
unchanged; school parity `PARITY OK`.

Next: the same guard on the other Go-owned tables that belong to a
country (cluster leadership, field routes), each with a recorded country.
The existing application's tables cannot be altered, so their isolation
stays the Go checks until they are Go's.

