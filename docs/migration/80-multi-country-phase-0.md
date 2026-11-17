# 80 · Edify Global, Phase 0: audit and architecture decisions

Owner instruction, 2026-11-17: *Edify Global — one platform, four countries
(Uganda, Kenya, Rwanda, Ethiopia), same programs, same roles,
country-specific configuration, securely isolated country data.* Phase 0 of
that instruction asks for an audit and the architecture decisions before any
schema change. This document is that Phase 0. The owner approved Phase 1
on §7's recommended defaults on 2026-11-17 ("Yes, start Phase 1"); what has
been built since, on the development copies only, is §8 to §10.

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

Still to come in Phase 1: the Admin pages for countries, settings and
memberships, which follow the Go backend.
