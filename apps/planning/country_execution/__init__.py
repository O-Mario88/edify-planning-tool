"""Country Execution & Completion Oversight (owner spec, 2026-09-28).

The second stage of Country Oversight. Planning Coverage proves the required
work was prepared; this proves it happened, on time, was reviewed and verified,
was closed, and completed the programme obligation. It monitors the platform's
own delivery spine and adds no workflow of its own:

* ``stages``   — ExecutionStageClassifier: canonical activity states read as
                 oversight stages (due, started, executed, reviewed, verified,
                 closed, returned, cancelled), stage-specific overdue labels,
                 the current owner of the next action, and start timing.
* ``dataset``  — the classified activities of a window, summed into cells by
                 every attribute the page filters on; the schedule trail's
                 original plan and carry-forward.
* ``service``  — CountryExecutionOversightService: filters, cache, the
                 Country → Programme Lead → CCEO → Partner fold, the KPIs,
                 charts, tables and lists; requirement-slot completion read
                 from the planning coverage service.
* ``followups``— ExecutionFollowUpService: "Follow Up with PL" for execution
                 gaps, on the same governed record as planning follow-ups.
"""
