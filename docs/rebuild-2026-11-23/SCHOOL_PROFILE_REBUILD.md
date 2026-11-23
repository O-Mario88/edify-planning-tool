# School Profile rebuild

Built in `web/src/components/profile/` from Go's `SchoolProfileService`. The presenter `lib/schoolProfileView.ts` arranges figures and calculates none.

**Delivered:** header with badges, facts and six actions plus an Actions menu; the eight existing tabs; Performance & Impact; SSA trend; Operations; Loans & Business Transformation; best and struggling intervention; Profile Insights; Needs Attention; Location & GPS with accuracy, source, verified-by and in-app directions; Core School tab.

**Data rules:** a school with no confirmed SSA reads Not Assessed, a missing earlier SSA reads Not Compared, and years with no reading are left off the trend.

**Limits**
- No school photo is stored, so a neutral placeholder is shown.
- The Core tab's Interventions card and readiness percentage from the reference are not drawn, because Go does not supply them.
- Reassign Owner still opens the existing application.
- The native Expo app still has its previous profile and still shows Go's 0.00.
