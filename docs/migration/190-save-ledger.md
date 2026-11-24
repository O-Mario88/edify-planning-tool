# 190 · Save ledger

Every save the web application offers, by the Django route it posts to, and where Go stands on it.
Built by `scripts/build_go_save_ledger.py` from the checked-in inventories; Go's status is kept by
hand in that script and changes only with evidence. *Proved* means compared with Django and replayed
with Django stopped.

- Saves: 225 destinations from 483 save controls.
- Go: 27 proved, 21 with unproved Go code, 167 still Django's, 1 retired on purpose, 9 made by Go's own services.
- Field staff can reach 119 saves that are not yet proved in Go.
- 92 controls post to a destination the inventory cannot read (set by a variable or script); they are listed by template at the end and must be classified by hand.

| Step | Saves |
|---|---|
| 3 field staff | 120 |
| 5 supervisors and leadership | 47 |
| 6 partners and loans | 21 |
| 7 HR, compliance and coaching | 5 |
| 8 finance and money | 22 |
| 9 admin and the rest | 10 |

## Step 3 field staff

| Route | Go | Size | Roles | Labels |
|---|---|---|---|---|
| `/activities/<str:activity_id>/salesforce-id/action` | proved | medium | 9 roles | Save Salesforce ID |
| `/activities/<str:activity_id>/start/action` | proved | small | 9 roles | Start activity |
| `/activities/<str:activity_id>/submit/action` | proved | small | 9 roles | Submit for review |
| `/activity-selection/cancel` | proved | small | 9 roles | Cancel {{ ready|length }} activit{{ ready|length|pluralize:"y,ies" }} |
| `/activity-selection/reschedule` | proved | small | 9 roles | Reschedule {{ ready|length }} activit{{ ready|length|pluralize:"y,ies" }} |
| `/core-schools/assign-partner/action` | proved | large | 6 roles | Assign to partner |
| `/core-schools/schedule-training/action` | proved | large | 6 roles | Schedule training |
| `/core-schools/schedule-visit/action` | proved | large | 6 roles | Schedule visit |
| `/debriefs/submit` | proved | medium | 10 roles | Submit Daily Debrief |
| `/extra-work/<str:assignment_id>/<str:action>` | proved | small | Admin, CCEO, CountryDirector, ImpactAssessment, Program Lead | Cancel; Return; Start |
| `/my-plan/<str:activity_id>/accountability` | proved | large | 9 roles | Submit for finance review |
| `/my-plan/<str:activity_id>/cancel` | proved | medium | 9 roles | Cancel activity |
| `/my-plan/<str:activity_id>/complete` | proved | large | 9 roles | Submit training + visit Submit completion |
| `/my-plan/<str:activity_id>/confirm-reimbursement-receipt` | proved | medium | 9 roles | Confirm receipt |
| `/my-plan/<str:activity_id>/edit` | proved | medium | 9 roles | Save changes |
| `/planning/assign-partner-action` | proved | large | 7 roles | Assign to partner |
| `/planning/schedule-action` | proved | large | 7 roles | Confirm & Schedule Activity; Schedule meeting Schedule training |
| `/planning/visit-requests/<str:activity_id>/<str:decision>` | proved | small | 7 roles | Approve visit; Decline |
| `/schools/<str:school_id>/assign-to-project` | proved | small | 7 roles | Assign to project |
| `/schools/<str:school_id>/take` | proved | small | 7 roles | Take {{ school.school_name }} as my school |
| `/today/snooze` | proved | small | Admin, CCEO, ImpactAssessment, Program Lead, ProjectCoordinator | {{ label }} |
| `/today/unsnooze` | proved | small | Admin, CCEO, ImpactAssessment, Program Lead, ProjectCoordinator | Undo |
| `/acting-leadership/<str:assignment_id>/cancel` | go-owned | small | 6 roles | Cancel appointment |
| `/acting-leadership/<str:assignment_id>/reschedule` | go-owned | small | 6 roles | Save month |
| `/acting-leadership/appoint` | go-owned | medium | 6 roles | Appoint {{ entry.short_label }}; Confirm Appointment |
| `/actions/<str:action_id>/<str:transition>` | django | medium | 15 roles | Acknowledge {{ r.school }}; Escalate {{ r.school }} to your supervisor |
| `/activities/<str:activity_id>/attendance/action` | django | medium | 9 roles | Save attendance |
| `/activities/<str:activity_id>/closure/close` | django | small | 7 roles | Close & Lock Activity Closing... |
| `/activities/<str:activity_id>/evidence/action` | django | medium | 9 roles | Submit |
| `/activities/<str:activity_id>/facilitator` | django | small | 9 roles | Save |
| `/activities/<str:activity_id>/partner-ssa-complete/action` | django | medium | 9 roles | Save SSA and complete |
| `/activities/<str:activity_id>/reopen` | django | small | 7 roles | Confirm Reopen Reopening... |
| `/activities/<str:activity_id>/ssa-upload/action` | django | medium | 9 roles | Save SSA scores |
| `/analytics/customize-dashboard` | django | medium | 10 roles | Save preferences |
| `/analytics/schedule-report` | django | medium | 10 roles | Send to inbox |
| `/api/documents/acknowledge/<str:acknowledgement_id>` | django | small | 16 roles | Change my answer to Agree; I Believe → Enter Edify I Accept → Continue; Submit response |
| `/api/documents/attest/<str:acknowledgement_id>` | django | small | 16 roles | I reviewed this outside the viewer |
| `/auth/switch-role` | go-owned | medium | 16 roles | {{ acting.label }} · {{ acting.period }}; {{ r.value }}; {{ role.value }} |
| `/change-password` | go-owned | medium | 16 roles | Set new password and continue |
| `/clusters/<str:cluster_id>/bulk-assign-drawer` | django | medium | 7 roles | Save schools to cluster |
| `/clusters/<str:cluster_id>/bulk-schedule-drawer` | django | medium | Admin, CCEO, CountryDirector, ImpactAssessment, Program Lead | Schedule the day |
| `/clusters/<str:cluster_id>/catchment-drawer` | django | medium | Admin, CCEO, CountryDirector, ImpactAssessment, Program Lead | Approve district |
| `/clusters/<str:cluster_id>/catchment/<str:catchment_id>/end` | django | medium | Admin, CCEO, CountryDirector, ImpactAssessment, Program Lead | End approval |
| `/clusters/<str:cluster_id>/delete` | django | small | 7 roles | Delete {{ cluster.name }} cluster |
| `/clusters/<str:cluster_id>/facilitator` | django | small | 7 roles | Save |
| `/clusters/<str:cluster_id>/schools/<str:school_id>/remove` | django | medium | 7 roles | Remove {{ s.name }} from this cluster |
| `/clusters/create` | django | medium | 7 roles | Create cluster |
| `/clusters/schedule-activity` | django | large | 7 roles | Schedule training Schedule meeting |
| `/core-schools/oversight/send` | django | large | 6 roles | Send to {{ r.responsible_first_name }} |
| `/core-schools/recommendations/<str:rec_id>/<str:action>` | django | medium | 6 roles | Accept; Defer; Reject |
| `/dashboard/notify-past-due/<str:activity_id>/` | django | small | 15 roles | Notify {{ row.owner }} to complete, reschedule, or cancel this activity |
| `/dashboard/pl-send-urgent-action` | django | medium | 15 roles | Send {{ row.school }} to {{ row.owner_name }} for action |
| `/dashboard/pl-week-send/<str:activity_id>/` | django | small | 15 roles | Remind {{ row.owner }} to complete this by entering the Salesforce ID |
| `/debriefs/action` | django | medium | 10 roles | + Create Action; Accept & Draft Activity; Ack |
| `/exports/prepare` | django | small | 16 roles | Download Excel |
| `/extra-work/assign` | unproved | small | Admin, CCEO, CountryDirector, ImpactAssessment, Program Lead | Assign work |
| `/help/articles/<slug:slug>/feedback` | django | small | 15 roles | Report missing step; Report outdated; Yes |
| `/help/manage/<slug:slug>/<slug:action>` | django | small | 15 roles | Product review; Publish; Submit |
| `/impact-briefs/<str:release_id>/shared` | django | small | 7 roles | Record as shared |
| `/logout` | go-owned | small | 16 roles | Log out; Sign out |
| `/messages/new/` | unproved | medium | 15 roles | Save Draft; Save draft; Send Message |
| `/messages/thread/<str:thread_id>/archive` | django | small | 15 roles | Archive |
| `/messages/thread/<str:thread_id>/reply` | django | small | 15 roles | Reply |
| `/messages/thread/<str:thread_id>/star` | django | small | 15 roles | Star conversation |
| `/my-plan/<str:activity_id>/invite-school` | django | small | 9 roles | Add {{ s.name }} to this session |
| `/my-professional-development/fund/<str:fund_request_id>/action` | django | medium | 9 roles | Clear accountability; Disburse funds; Place on hold |
| `/my-professional-development/request` | unproved | large | 9 roles | Cancel this draft; Save draft; Submit for approval |
| `/my-professional-development/request/<str:request_id>/action` | django | medium | 9 roles | Approve & send to HR; Approve & send to the Country Director; Authorize & send to Accounting |
| `/my-professional-development/request/<str:request_id>/certificate` | django | small | 9 roles | Upload another Upload proof; Upload certificate |
| `/my-targets/mscs` | unproved | small | 7 roles | Submit for Review |
| `/notifications` | unproved | medium | 15 roles | Archive; Archive All Read; Mark All Read |
| `/notifications/<str:notif_id>/read` | go-owned | small | 15 roles | Mark as read |
| `/notifications/mark-all-read` | go-owned | small | 15 roles | Mark all as read |
| `/notifications/settings` | go-owned | small | 15 roles | Save |
| `/planning/bulk-action` | django | large | 7 roles | Assign {{ assignable|length }} school{{ assignable|length|pluralize }}; Export Selected |
| `/planning/bulk-schedule` | django | medium | 7 roles | Schedule {{ schools|length }} school{{ schools|length|pluralize }} |
| `/planning/undo` | django | small | 7 roles | Undo; Undo: {{ change.summary }} |
| `/priorities/ssa-mapping/<str:item_id>/save` | django | medium | 6 roles | Save draft; Submit for review |
| `/projects/<str:project_id>/delete` | django | medium | 6 roles | Delete Project |
| `/projects/<str:project_id>/edit` | django | medium | 6 roles | Save changes |
| `/projects/<str:project_id>/schools/assign` | django | small | 6 roles | Add School |
| `/projects/<str:project_id>/schools/bulk-assign-drawer` | django | large | 6 roles | Add selected schools |
| `/projects/<str:project_id>/schools/bulk-withdraw` | django | medium | 6 roles | Withdraw {{ withdrawable|length }} school{{ withdrawable|length|pluralize }} |
| `/projects/<str:project_id>/staff/assign` | django | small | 6 roles | Assign Project priority |
| `/projects/capacity/set` | unproved | medium | Admin, ImpactAssessment, ProjectCoordinator | Choose a project {{ p.name }} ({{ p.code }}); Save Capacity |
| `/projects/capacity/withdraw` | unproved | medium | 6 roles | Withdraw School |
| `/projects/create/action` | django | small | 6 roles | Create proposed project |
| `/projects/planning/bulk-partner` | unproved | large | 6 roles | Assign {{ assignments|length }} school{{ assignments|length|pluralize }} |
| `/projects/planning/bulk-schedule` | django | medium | 6 roles | Schedule {{ assignments|length }} school{{ assignments|length|pluralize }} |
| `/schools/<str:school_id>/add-to-cluster` | django | small | 7 roles | Change cluster Add to cluster |
| `/schools/<str:school_id>/change-type` | django | small | 7 roles | Save |
| `/schools/<str:school_id>/close` | django | small | 7 roles | Close school |
| `/schools/<str:school_id>/edit-drawer` | django | large | 7 roles | Save school |
| `/schools/<str:school_id>/reopen` | django | small | 7 roles | Reopen school |
| `/schools/<str:school_id>/ssa-entry` | django | medium | 7 roles | Save SSA |
| `/schools/<str:school_id>/transfer-owner` | django | medium | 7 roles | Reassign owner |
| `/schools/bulk-assign-cluster` | django | small | 7 roles | Assign cluster |
| `/schools/bulk-assign-project` | django | large | 7 roles | Add to project; Assign project |
| `/schools/bulk-match-staff` | django | small | 7 roles | Match staff |
| `/schools/bulk-transfer-owner` | django | medium | 7 roles | Reassign ownership |
| `/schools/create-drawer` | django | medium | 7 roles | Create school; Save and add SSA score |
| `/settings/activity-catalogue/<str:item_id>/edit` | django | medium | 16 roles | Save training |
| `/settings/activity-catalogue/<str:item_id>/lifecycle` | django | small | 16 roles | Save lifecycle |
| `/settings/activity-catalogue/new` | unproved | medium | 16 roles | Add activity |
| `/settings/activity-catalogue/reviews/<str:review_id>/resolve` | django | medium | 16 roles | Resolve |
| `/ssa/manual/` | unproved | medium | 6 roles | Save SSA Score |
| `/ssa/verification/` | unproved | large | 6 roles | Confirm |
| `/staff-activity/follow-ups/<str:follow_up_id>/<slug:action>` | django | small | 15 roles | {{ a.label }} |
| `/strategic-priorities/cycles/<str:cycle_id>/approve` | django | small | 16 roles | Approve FY{{ cycle.financial_year }} cycle |
| `/strategic-priorities/milestones/<str:milestone_id>/allocate` | django | small | 16 roles | Allocate and approve |
| `/strategic-priorities/milestones/<str:milestone_id>/approve` | django | small | 16 roles | Approve definition |
| `/strategic-priorities/milestones/<str:milestone_id>/define` | django | small | 16 roles | Save definition for approval |
| `/strategic-priorities/milestones/<str:milestone_id>/edit` | django | small | 16 roles | Save targets |
| `/support` | unproved | small | 15 roles | Send to the platform team |
| `/today/act` | django | small | Admin, CCEO, ImpactAssessment, Program Lead, ProjectCoordinator | {{ op.label }} |
| `/today/action` | django | medium | Admin, CCEO, ImpactAssessment, Program Lead, ProjectCoordinator | Accept week; Dismiss; Regenerate draft Prepare my week |
| `/work-plan/add/action` | django | medium | 16 roles | Add to my plan |
| `/work-plan/add/preview` | django | medium | 16 roles | My own district {{ district.name }}; Select an approved activity {{ item.display_name }}; {{ date_prefill }} |
| `/work-plan/rvp-decision` | django | small | 16 roles | Approve & lock; Return |
| `/work-plan/submit-to-rvp` | django | small | 16 roles | Resolve the readiness issues first |

## Step 5 supervisors and leadership

| Route | Go | Size | Roles | Labels |
|---|---|---|---|---|
| `/admin-panel/staff-setup-queue` | unproved | medium | Admin, CountryDirector, HumanResources, ImpactAssessment | Ignore; Match |
| `/cluster-oversight/scoring` | unproved | medium | Admin, CountryDirector, ImpactAssessment | Save Weights |
| `/country-planning-oversight/execution/follow-up` | django | medium | Admin, CountryDirector, ImpactAssessment, RegionalVicePresident | Send to {{ lead_name|default:"the Programme Lead" }} |
| `/country-planning-oversight/execution/snapshots/<str:snapshot_id>` | django | medium | Admin, CountryDirector, ImpactAssessment, RegionalVicePresident | Record a revision |
| `/country-planning-oversight/follow-up` | django | medium | Admin, CountryDirector, ImpactAssessment, RegionalVicePresident | Send to {{ lead_name|default:"the Programme Lead" }} |
| `/country-planning-oversight/follow-up/<str:followup_id>/<str:action>` | django | small | Admin, CountryDirector, ImpactAssessment, RegionalVicePresident | Cancel the follow-up; Close; Escalate |
| `/country-planning-oversight/send` | django | medium | Admin, CountryDirector, ImpactAssessment, RegionalVicePresident | Send; Send to PL |
| `/cpd-learning/action` | django | large | 6 roles | Approve; Remind All ({{ g.count }}); Remind All to Apply ({{ not_applied_count }}) |
| `/cpd-learning/adjust-allocation` | django | medium | 6 roles | Save allocation |
| `/dashboard/cd-approve` | django | small | Admin, CountryDirector, ImpactAssessment | Approve |
| `/dashboard/cd-return` | django | small | Admin, CountryDirector, ImpactAssessment | Return |
| `/data-quality/issue/<str:issue_id>/action` | django | small | Admin, ImpactAssessment | Assign to me; Resolve |
| `/documents/<slug:slug>/<str:action>` | django | medium | Admin, CountryDirector, HumanResources, ImpactAssessment, RegionalVicePresident | Approve; Publish; Return for correction |
| `/documents/<slug:slug>/versions/new` | django | small | Admin, CountryDirector, HumanResources, ImpactAssessment, RegionalVicePresident | Upload version |
| `/ia/duplicates/<str:duplicate_id>/action` | django | small | Admin, ImpactAssessment | Flag Investigation; Ignore Flag; Return to Plan |
| `/ia/impact-report/download` | django | medium | Admin, CountryDirector, ImpactAssessment | Download today's live evidence annex (draft) |
| `/ia/impact-reports/<str:report_id>/correct` | django | small | Admin, CountryDirector, ImpactAssessment, RegionalVicePresident | Start a correction |
| `/ia/impact-reports/<str:report_id>/release/leadership` | django | small | Admin, CountryDirector, ImpactAssessment, RegionalVicePresident | Release to country leadership |
| `/ia/impact-reports/<str:report_id>/submit` | django | small | Admin, CountryDirector, ImpactAssessment, RegionalVicePresident | Submit for review |
| `/ia/impact-reports/<str:report_id>/withdraw` | django | small | Admin, CountryDirector, ImpactAssessment, RegionalVicePresident | Withdraw |
| `/ia/partner-evidence/<str:activity_id>/complete-action` | django | small | Admin, ImpactAssessment | Record ID and complete |
| `/ia/partner-evidence/<str:activity_id>/return-action` | django | small | Admin, ImpactAssessment | Return to partner |
| `/ia/samples/<str:sample_id>/field-check` | django | small | Admin, CountryDirector, ImpactAssessment | Field back-check |
| `/ia/samples/<str:sample_id>/outcome` | django | medium | Admin, CountryDirector, ImpactAssessment | Confirm |
| `/ia/samples/<str:sample_id>/resolve` | django | small | Admin, CountryDirector, ImpactAssessment | Resolve |
| `/ia/samples/draw` | django | small | Admin, CountryDirector, ImpactAssessment | Draw this week now |
| `/ia/school-evidence/learning/upload` | django | small | Admin, CountryDirector, ImpactAssessment | Upload results |
| `/ia/verification/<str:activity_id>/return` | django | medium | Admin, CountryDirector, ImpactAssessment | Return to officer |
| `/ia/verification/<str:activity_id>/verify` | django | medium | Admin, CountryDirector, ImpactAssessment | Verified |
| `/planning-follow-ups/<str:followup_id>/<str:action>` | django | medium | 7 roles | Acknowledge; Return to the Country Director; Save |
| `/planning-monitor/send` | django | medium | 6 roles | Ask {{ school.officer_name }} to plan for {{ school.name }}: {{ monitor_gap_label|lower }} |
| `/planning/fiscal-years` | unproved | medium | Admin, CountryDirector, ImpactAssessment | Allow without training Require a training; Open FY{{ next_fy }} |
| `/policy-compliance/comments/<str:comment_id>` | django | small | 6 roles | Send |
| `/quality-checks` | unproved | large | Admin, CountryDirector, ImpactAssessment, Program Lead | Acknowledge |
| `/rvp/annual/<str:budget_id>/action` | django | small | Admin, ImpactAssessment, RegionalVicePresident | Approve & Lock; Approve & lock; Return |
| `/rvp/strategy-note` | django | small | Admin, ImpactAssessment, RegionalVicePresident | Save Strategy Note |
| `/schools/upload` | unproved | small | Admin, ImpactAssessment | Upload Schools |
| `/staff-activity/people/<str:person_id>/follow-up/send` | django | medium | Admin, CountryDirector, ImpactAssessment, Program Lead | Send follow-up |
| `/target-distribution/action` | django | medium | Admin, CountryDirector, ImpactAssessment | Approve & distribute; Confirm source figure; Publish FY{{ fy }} master |
| `/target-distribution/team/action` | django | medium | Admin, ImpactAssessment, Program Lead | Approve & distribute; Approve spread; Save draft |
| `/team-planning-oversight/send` | django | medium | 7 roles | Send to {{ risk.owner_name|default:"the owner" }} |
| `/team-targets/catchup` | django | medium | 6 roles | Submit catch-up plan |
| `/team-targets/catchup/<str:plan_id>/action` | django | small | 6 roles | Approve; Return |
| `/training-ceilings/country/set` | unproved | medium | 7 roles | Remove Country Ceiling; Save Country Ceiling |
| `/training-ceilings/set` | unproved | medium | 7 roles | Remove ceiling; Save ceiling |
| `/uploads/bulk-completion/batch/<str:batch_id>/cancel` | django | small | Admin, ImpactAssessment | Cancel Upload |
| `/uploads/bulk-completion/batch/<str:batch_id>/confirm` | django | small | Admin, ImpactAssessment | Confirm Bulk Completion ({{ summary.ready }}) |

## Step 6 partners and loans

| Route | Go | Size | Roles | Labels |
|---|---|---|---|---|
| `/loan-applications/<str:application_id>/follow-up` | django | small | 7 roles | Save follow-up |
| `/loans/<str:loan_id>/ia-validation` | django | small | 7 roles | Submit IA decision |
| `/loans/<str:loan_id>/salesforce-confirmation` | django | small | 7 roles | Confirm & complete |
| `/partner-oversight/allowance-grant` | django | small | 8 roles | Grant allowance |
| `/partner-oversight/return/submit` | django | small | 8 roles | Return to Partner |
| `/partner-oversight/send` | django | medium | 8 roles | Escalate; {{ risk.send_label }} |
| `/partner-oversight/verify/submit` | django | small | 8 roles | Verify & Confirm |
| `/partner-oversight/withdraw/bulk` | unproved | medium | 8 roles | Withdraw {{ withdraw_count }} · request {{ request_count }} Send {{ request_count }} to Program Lead Withdraw {{ withdraw_count }} school{{ withdraw_count|plura |
| `/partner-oversight/withdraw/review` | django | small | 8 roles | Approve; Reject |
| `/partner/activities/<str:activity_id>/delivered-by` | django | medium | Admin, ImpactAssessment, PartnerAdmin, PartnerFieldOfficer | Save |
| `/partner/activities/<str:activity_id>/start-action` | django | small | Admin, ImpactAssessment, PartnerAdmin, PartnerFieldOfficer | Complete; Start Activity |
| `/partner/activities/<str:activity_id>/submit-action` | django | medium | Admin, ImpactAssessment, PartnerAdmin, PartnerFieldOfficer | Submit Evidence to IA |
| `/partner/assignments/<str:assignment_id>/return-action` | django | small | Admin, ImpactAssessment, PartnerAdmin, PartnerFieldOfficer | Return to staff |
| `/partner/assignments/<str:assignment_id>/schedule-action` | django | medium | Admin, ImpactAssessment, PartnerAdmin, PartnerFieldOfficer | Schedule delivery |
| `/partner/invoices` | django | medium | Admin, ImpactAssessment, PartnerAdmin, PartnerFieldOfficer | Send invoice{{ basis.by_lead|length|pluralize }} |
| `/partners/<str:partner_id>/edit-drawer` | django | medium | 15 roles | Save details |
| `/partners/<str:partner_id>/members` | django | small | 15 roles | Add to roster; Remove {{ m.name }} from the roster |
| `/partners/<str:partner_id>/members/<str:member_id>/login` | django | medium | 15 roles | Activate the login of {{ m.name }}; Create login; Deactivate the login of {{ m.name }} |
| `/partners/<str:partner_id>/members/<str:member_id>/schools` | django | medium | 15 roles | Save schools |
| `/partners/<str:partner_id>/status` | django | small | 15 roles | Deactivate Activate |
| `/partners/<str:partner_id>/user-setup` | django | medium | 15 roles | Save login setup |

## Step 7 HR, compliance and coaching

| Route | Go | Size | Roles | Labels |
|---|---|---|---|---|
| `/hr/performance-cycle/action` | django | large | Admin, HumanResources, ImpactAssessment | Activate & freeze snapshots; Approve & lock; Close window |
| `/performance-conversation/<str:review_id>/agree-priorities` | django | small | 9 roles | Agree these priorities |
| `/performance-conversation/<str:review_id>/sign-off` | django | small | 9 roles | Sign off & lock |
| `/performance-conversation/priority/<str:priority_id>/save` | django | medium | 9 roles | Save manager review; Save my reflection; Save rating |
| `/performance-conversation/value/<str:commitment_id>/save` | django | small | 9 roles | Save commitment; Save observation |

## Step 8 finance and money

| Route | Go | Size | Roles | Labels |
|---|---|---|---|---|
| `/fund-requests/receipt-confirm` | proved | small | 7 roles | Confirm Receipt |
| `/fund-requests/weekly/<str:request_id>/confirm` | proved | small | 7 roles | Send for Approval |
| `/fund-requests/weekly/<str:request_id>/confirm-receipt` | proved | small | 7 roles | Fund Received |
| `/fund-requests/weekly/<str:request_id>/not-requested` | proved | small | 7 roles | No Advance This Week |
| `/fund-requests/weekly/<str:request_id>/self-funded` | proved | small | 7 roles | Self Fund |
| `/accounts/activities/<str:activity_id>/netsuite-id` | django | small | Accountant, Admin, ImpactAssessment | Save & Reconcile ID |
| `/accounts/monthly-request/action` | django | small | 6 roles | {{ fetch_label }}; {{ submit_label }}; {{ submit_rvp_label|default:"Send to RVP for Approval" }} |
| `/accounts/partner-invoices/<str:invoice_id>/pay` | django | small | Accountant, Admin, ImpactAssessment | Pay Partner |
| `/cost-settings/add` | unproved | medium | Admin, CountryDirector, ImpactAssessment | Add cost |
| `/cost-settings/carry-forward` | django | small | Admin, CountryDirector, ImpactAssessment | Carry Forward FY{{ carry_forward_source.fy }} Rates |
| `/cost-settings/initialize-default` | django | small | Admin, CountryDirector, ImpactAssessment | Initialize Default Catalogue |
| `/cost-settings/row/<str:key>` | django | medium | Admin, CountryDirector, ImpactAssessment | Save rate |
| `/country-budget/action` | django | medium | Accountant, Admin, CountryDirector, ImpactAssessment, RegionalVicePresident | Add admin item; Add item; Approve |
| `/disbursements/action` | django | medium | Accountant, Admin, ImpactAssessment | Disburse funds; Place on hold; Release Hold |
| `/finance/actions/disburse_advance` | django | small | Accountant, Admin, ImpactAssessment | Disburse advance Clear payment Process reimbursement Confirm clearance Return for correction Confirm action |
| `/fund-approvals/action` | django | medium | Admin, CountryDirector, ImpactAssessment, Program Lead | Resolve: {{ selected.issues|join:'; ' }} {{ selected.waiting_hint }}; Return for review |
| `/fund-approvals/invoices/<str:invoice_id>/action` | django | small | Admin, CountryDirector, ImpactAssessment, Program Lead | Confirm & Send to Accountant; Return |
| `/fund-requests/advances/<str:advance_id>/pl-approve` | django | small | 7 roles | Approve |
| `/fund-requests/advances/<str:advance_id>/pl-return` | django | small | 7 roles | Return |
| `/fund-requests/generate-request` | retired | small | 7 roles | Take Action |
| `/fund-requests/weekly/<str:request_id>/approve` | django | small | 7 roles | Approve |
| `/fund-requests/weekly/<str:request_id>/return` | django | small | 7 roles | Return request |

## Step 9 admin and the rest

| Route | Go | Size | Roles | Labels |
|---|---|---|---|---|
| `/admin-ops/incidents/<str:incident_id>/acknowledge` | django | small | Admin | Acknowledge Incident |
| `/admin-ops/incidents/<str:incident_id>/resolve` | django | small | Admin | Resolve |
| `/admin-ops/tickets/<str:ticket_id>/resolve` | django | small | Admin | Resolve |
| `/admin-ops/tickets/<str:ticket_id>/triage` | django | small | Admin | Triage |
| `/admin-ops/work-items/<str:item_id>/complete` | django | small | Admin | Complete |
| `/admin-ops/work-items/<str:item_id>/schedule` | django | small | Admin | Schedule |
| `/admin-ops/work-items/<str:item_id>/start` | django | small | Admin | {{ item.next_action|default:"Start" }} |
| `/admin/(?P<url>.*)$` | django | unknown |  | Create District; Resend Alert |
| `/data-repair/<str:key>/apply` | django | small | Admin | Apply Repair Refer for Correction |
| `/system-health/notifications/test` | django | small | Admin | Send me a test notification |

## Controls whose destination the inventory cannot read

| Template | Controls |
|---|---|
| `pages/admin/user_detail.html` | 7 |
| `pages/admin/users.html` | 7 |
| `pages/leave/public_holidays.html` | 5 |
| `partials/leave/impact_panel.html` | 5 |
| `pages/admin/region_district_setup.html` | 4 |
| `pages/admin/unmatched_ssa_queue.html` | 4 |
| `pages/debriefs/weekly_report.html` | 4 |
| `pages/accounts/budget_amendments.html` | 3 |
| `partials/ia/outcomes.html` | 3 |
| `pages/auth/mfa_verify.html` | 2 |
| `pages/escalations/_table.html` | 2 |
| `pages/leave/personal_time_off.html` | 2 |
| `pages/schools/ownership_transfers.html` | 2 |
| `pages/schools/upload_preview.html` | 2 |
| `pages/settings/two_step_app.html` | 2 |
| `pages/team_performance/country_targets.html` | 2 |
| `partials/core_schools/champion_review_drawer.html` | 2 |
| `partials/ia/impact_reports_table.html` | 2 |
| `pages/accounts/accountability.html` | 1 |
| `pages/accounts/partner_payments.html` | 1 |
| `pages/accounts/ready_for_advance.html` | 1 |
| `pages/admin/duplicate_review.html` | 1 |
| `pages/auth/login.html` | 1 |
| `pages/auth/reset_password.html` | 1 |
| `pages/bulk_completion/upload.html` | 1 |
| `pages/business_transformation/loan_application_public.html` | 1 |
| `pages/calendar/index.html` | 1 |
| `pages/escalations/index.html` | 1 |
| `pages/help/edit_article.html` | 1 |
| `pages/hr/pulse_respond.html` | 1 |
| `pages/ia/framework.html` | 1 |
| `pages/profile/index.html` | 1 |
| `pages/quality_checks/index.html` | 1 |
| `pages/settings/index.html` | 1 |
| `pages/ssa/upload_center.html` | 1 |
| `pages/ssa/upload_preview.html` | 1 |
| `partials/admin/add_user_drawer.html` | 1 |
| `partials/admin/reset_password_drawer.html` | 1 |
| `partials/clusters/edit_cluster_drawer.html` | 1 |
| `partials/decisions/insight_row.html` | 1 |
| `partials/finance/fund_workspace.html` | 1 |
| `partials/hr/form_drawer.html` | 1 |
| `partials/ia/reports_view.html` | 1 |
| `partials/leave/request_leave_drawer.html` | 1 |
| `partials/my_plan/pl_review_drawer.html` | 1 |
| `partials/oversight/resolve_return_drawer.html` | 1 |
| `partials/oversight/withdrawal_drawer.html` | 1 |
| `partials/partners/create_partner_drawer.html` | 1 |
| `partials/planning/schedule_drawer.html` | 1 |
| `partials/profiles/_decisions.html` | 1 |
