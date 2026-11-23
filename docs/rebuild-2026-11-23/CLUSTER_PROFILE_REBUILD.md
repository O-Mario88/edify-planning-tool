# Cluster Profile rebuild

Go: `schoolprofile/cluster_profile*.go`, `clusterpage/export_profile.go`. Web: `components/profile/Cluster*`, routes `/clusters/[id]` and `/clusters/[id]/profile`.

**Delivered:** header band, seven tabs, seven KPIs, SSA over assessed schools only, histories (SSA, coverage, visits, trainings, action closure), SSA readiness by school, activities, meeting attendance with repeated absence, data-derived insights and recommended actions, and a member table with search, filters, sort, ticks, row actions, CSV export and an expandable school drill-down.

**Verified on the private DB:** Edit Details saved and showed in the header; a cluster meeting was scheduled (4 to 5 rows); an officer outside the cluster gets not found.

**Limits**
- Delete Cluster is shown disabled with its reason; deletion stays on the existing application.
- Training coverage counts in-school trainings, not group attendance.
- There was no phone reference for this page, so its phone layout follows the School Profile's phone pattern.
- The reference shows 0.00 for unassessed clusters; the written rule was followed and it reads Not Assessed.
