"""Country Planning Oversight — the requirement read model behind the CD's page.

What the country OWES a year (every eligible school's visit and training
slots), what staff planned against it, what Partners were handed and what they
dated, what remains, and who holds each gap. One canonical layer, split by
concern:

* ``policy``        — the governed programme configuration: school families,
                      per-family visit and training slots, staff ceilings and
                      the activity states that count as planned.
* ``requirements``  — PlanningRequirementService: the eligible portfolio, its
                      families and each owner's capacity allocation.
* ``coverage``      — PlanningCoverageService: per-school facts read from the
                      canonical activity, assignment, roster and cluster
                      records, and the slot claims made from them.
* ``hierarchy``     — PlanningHierarchyService: who holds each school, folded
                      into Programme Lead, CCEO, PL-personal and Partner rows.
* ``service``       — CountryPlanningOversightService: filters, the cached
                      dataset, the strip, the charts, the table and exports.
* ``followups``     — PlanningOversightFollowUpService: the Country Director's
                      governed "Follow Up with PL" workflow.
* ``data_quality``  — Impact Assessment's reconciliation checks.

It writes nothing about planning. Every number is folded from real records;
planned is never verified, an assignment is never a schedule, and a school or
a slot is counted once.
"""
