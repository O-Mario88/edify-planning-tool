# Daily staff cost allocation

Staff school visits, including core and SSA visits, join the responsible staff
member's dated activity group. Single-day staff training, cluster meetings and
field activities share that group; an automatically paired evidence visit is
not a second funded journey. Partner delivery retains its separate recipe.

For school-visit days, the daily components are:

- Primary district: transport and staff lunch.
- Secondary district: transport, breakfast, lunch, dinner and accommodation.
- Mixed primary/secondary day: use the secondary total once, divided across
  every active activity that day. Primary-district activities on that day
  receive the same share. Removing the last secondary activity restores
  primary pricing. Approved route-group rules still apply when multiple
  secondary districts are scheduled together.

The configured catalogue amounts are summed once and split across active
activities in the group. Each component is divided with deterministic integer
rounding, preserving the full daily total. Cancelled, deferred and rejected
activities do not contribute to the divisor. Session-specific costs stay with
the session; the existing catered-session meal policy still applies.

The primary district in User Configuration determines the staff member's home
rates. Other destinations use secondary rates. Existing users without a primary
district retain the legacy district classification until their profile is set.
The secondary district assignments on that page also define portfolio access.

Saved cost lines, allocation metadata and snapshots supply My Plan estimates,
budgets, Work Plan and weekly/monthly requests. Existing operational/minimum-rate
and staff/vendor payment distinctions are retained.

## Refresh an existing installation

After deploying, inspect the affected fiscal year:

```sh
python manage.py refresh_daily_cost_allocations --fy 2026
```

Apply the reported editable repairs:

```sh
python manage.py refresh_daily_cost_allocations --fy 2026 --apply
```

The command reclassifies and reprices editable groups and attaches older
standalone staff activities (including core visits). It skips locked requests,
completed groups, settled transport and unapproved secondary district combinations.
Approved/disbursed history is preserved. A follow-up dry run should report only
blocked historical groups, if any. Re-run after changing staff district
configuration when existing editable plans need updating.
