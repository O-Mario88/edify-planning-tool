"""Plain-language teaching structure shared by every Help Center guide.

The catalog supplies the feature-specific purpose and first action.  This
module adds the practical context people need to understand how that feature
fits into their day-to-day work before they start clicking buttons.
"""

from __future__ import annotations

from typing import Iterable


def section(heading: str, body: str = "", items: Iterable[str] | None = None) -> dict:
    return {"heading": heading, "body": body, "items": list(items or [])}


CATEGORY_LESSONS = {
    "Getting Started": {
        "explainer": "This part of Edify helps you get comfortable with the workspace, your role and the records you will use most often.",
        "screen": [
            "Your role decides which pages and actions you can see.",
            "Each page is connected to a real record, such as a school, activity, request or person.",
            "The status and next action on that record tell you what to do now.",
        ],
        "checks": "Edify keeps your work in the right place and only offers actions that match your role and the record's current stage.",
        "connection": "Start with the record closest to the work you need to do. From there, use the status, To-Dos and notifications to move to the next step.",
        "tips": [
            "Use the Help for this page button whenever a screen is unfamiliar.",
            "Read the status before taking an action.",
            "Avoid creating a second record when the existing one can be corrected.",
        ],
    },
    "Role Guides": {
        "explainer": "This guide explains the work that belongs to your role, the pages you will normally use and the people you work with next.",
        "screen": [
            "Your dashboard brings together tasks and information that matter to your role.",
            "Lists and queues show only the work you are allowed to see.",
            "The same record may look different to another role because each person has a different job in the process.",
        ],
        "checks": "Edify separates responsibilities so that planning, checking, approval and payment are handled by the right people.",
        "connection": "When your part is complete, Edify records it and makes the next step visible to the next responsible person.",
        "tips": [
            "Use your role guide as your daily starting point.",
            "If an action is missing, check the record status and ownership first.",
            "Use a clear note when you return work so the next person knows what to fix.",
        ],
    },
    "SSA and School Improvement": {
        "explainer": "This area keeps school information and assessment findings together so plans are based on the right school and the right need.",
        "screen": [
            "School records show the identity, location and current assignment of a school.",
            "SSA information helps you understand needs, patterns and recommendations.",
            "Quality messages point out duplicate, missing or unmatched information before it is used.",
        ],
        "checks": "Edify checks school identifiers, matching and eligibility so that planning is based on real, reliable information.",
        "connection": "Once school and SSA information is ready, it can guide clustering, planning, Core School work and impact review.",
        "tips": [
            "Always check the School ID before changing or uploading information.",
            "Fix the named data issue on the original record instead of making a similar new record.",
            "Use the selected financial year when comparing SSA information.",
        ],
    },
    "Planning and Field Operations": {
        "explainer": "This area turns school needs into planned field work, then helps the responsible person deliver and follow up on that work.",
        "screen": [
            "Planning pages collect the school or cluster, purpose, date, delivery person and any required details.",
            "My Plan gives each responsible person a practical list of work and the next action for each activity.",
            "Route, calendar and availability information help prevent impossible or conflicting field days.",
        ],
        "checks": "Edify checks dates, permissions, route rules, availability and required information before it lets a plan move forward.",
        "connection": "A planned activity moves into delivery, evidence, verification and—when money is involved—finance clearance.",
        "tips": [
            "Plan from the real school or cluster record.",
            "Check the date, owner and cost before saving.",
            "After delivery, return to the same activity for evidence and follow-up.",
        ],
    },
    "Evidence and Verification": {
        "explainer": "This area keeps proof of completed work together and helps the right reviewer confirm that the activity is ready to move on.",
        "screen": [
            "The activity shows the evidence, attendance and identifiers that belong to that work.",
            "Evidence previews help you check that a file can be read before review.",
            "The verification queue shows work waiting for IA to clear or return.",
        ],
        "checks": "Edify checks that required evidence, identifiers and activity details are present before an activity can pass verification.",
        "connection": "Verified work can continue to finance, reporting and completion. Returned work goes back to the responsible person with a reason.",
        "tips": [
            "Attach proof to the correct activity, not a similar activity.",
            "Read a return reason carefully and fix only what it names.",
            "Do not treat a file upload as final until its preview and status look right.",
        ],
    },
    "Finance and Accountability": {
        "explainer": "This area follows money from a planned activity through request, approval, payment, receipts and final clearance.",
        "screen": [
            "Cost and request pages show what work is being funded and where it is in the approval process.",
            "Disbursement and accountability pages keep the amount, payment reference, receipts and explanation together.",
            "Status messages show whether the next step belongs to the requester, approver or accountant.",
        ],
        "checks": "Edify checks that work is eligible, approved and supported by the required records before it can move to payment or closure.",
        "connection": "Finance records stay linked to the original activity so a payment, return or reimbursement can be followed from start to finish.",
        "tips": [
            "Check the source activity and amount before approving or paying.",
            "Keep receipts and reference numbers on the same record.",
            "If money does not match, use the return or reimbursement path shown by Edify.",
        ],
    },
    "Targets, Analytics and Performance": {
        "explainer": "This area helps you see progress, understand gaps and turn the information into a clear next action.",
        "screen": [
            "Dashboards summarise the work and results you are allowed to see.",
            "Targets link progress to real activities and the selected financial year.",
            "Drill-down links take you from a number to the underlying record when you need detail.",
        ],
        "checks": "Edify calculates results from the records that qualify for the selected period instead of asking people to type in a result by hand.",
        "connection": "Use a gap or trend to start a catch-up plan, assign a follow-up action or raise an issue with the right leader.",
        "tips": [
            "Set the right period and work area before reading a result.",
            "Open the linked records before making a decision.",
            "Use a catch-up action to improve work; do not change a dashboard number directly.",
        ],
    },
    "HR and People Operations": {
        "explainer": "This area supports people records, leave, coverage, development and performance work without mixing it into operational or finance records.",
        "screen": [
            "People pages keep the relevant employee, request, approval and follow-up information together.",
            "Leave and coverage pages show dates, conflicts and the person covering work.",
            "HR queues make it clear when someone needs to approve, return or complete a people-related task.",
        ],
        "checks": "Edify checks required details, dates, approvals and coverage information before a people process moves forward.",
        "connection": "Approved people actions update the right HR record while operational work continues with clear ownership and coverage.",
        "tips": [
            "Give complete dates and coverage details when making a request.",
            "Use return reasons to correct the same request.",
            "Keep sensitive people information in the authorised record.",
        ],
    },
    "Administration and Security": {
        "explainer": "This area helps Admins keep access, records and the overall system safe and reliable.",
        "screen": [
            "Account and role settings show who can use Edify and which work area they are responsible for.",
            "System Health highlights things that may need attention.",
            "The Audit Log helps authorised people understand what happened without changing the history.",
        ],
        "checks": "Edify records important changes and limits access so people see only the work needed for their role.",
        "connection": "Good administration keeps every other area of Edify available, appropriately restricted and easier to support.",
        "tips": [
            "Give the smallest role and work area needed for the person's job.",
            "Use the audit history to understand a problem before changing anything.",
            "Never share account credentials or use another person's account.",
        ],
    },
    "Troubleshooting": {
        "explainer": "This guide helps you understand a message, find the real cause and correct the original record safely.",
        "screen": [
            "The message on the page names the missing information, failed check or person who needs to act.",
            "The record status shows whether it needs correction, review or a different role.",
            "Related links take you back to the same item instead of starting over.",
        ],
        "checks": "Edify stops unsafe or incomplete actions so that the record can be corrected before it affects the rest of the process.",
        "connection": "Once the named issue is fixed on the original record, the usual workflow can continue from the correct point.",
        "tips": [
            "Read the full message before retrying.",
            "Correct the original record instead of creating a duplicate.",
            "Escalate only the information needed to the named owner or support person.",
        ],
    },
    "Glossary": {
        "explainer": "This reference explains the words, identifiers and statuses you see while using Edify.",
        "screen": [
            "Each term gives a plain explanation and, where useful, a link to the related guide.",
            "Status names tell you where a record is in its journey.",
            "Identifiers help you match the right school, activity or finance record.",
        ],
        "checks": "Edify keeps different identifiers and statuses separate so that records can be matched and followed correctly.",
        "connection": "Use the glossary when a word or status is unfamiliar, then return to the related guide for the next action.",
        "tips": [
            "Use the exact identifier shown on the record.",
            "Do not swap a School ID, Salesforce ID or finance reference.",
            "Check the status words as well as the colour on screen.",
        ],
    },
}


def _specific_lesson(title: str, category: str) -> tuple[str, list[str]]:
    """Add practical, feature-level detail without exposing implementation details."""
    name = title.lower()
    if "my plan" in name:
        return (
            "My Plan is your working list. It brings together activities assigned to you and shows the most useful next step on each one.",
            [
                "Open an activity card to see its details and current status.",
                "Use the next action on the card rather than guessing which page to visit.",
                "Return to the same activity after each step so its history stays complete.",
            ],
        )
    if any(
        word in name
        for word in ("planning", "schedule", "rescheduling", "route", "visit batch")
    ):
        return (
            "Planning turns a real school or cluster need into work that can be delivered on a possible date by the right person.",
            [
                "Choose the correct school or cluster first.",
                "Add the purpose, delivery owner and date before saving.",
                "Use any route, date or cost message to adjust the plan before trying again.",
            ],
        )
    if any(word in name for word in ("evidence", "ia verification", "salesforce")):
        return (
            "Verification makes sure completed work has the right proof and identifiers before it is counted as ready for the next stage.",
            [
                "Check that the evidence belongs to this exact activity.",
                "Make sure the required identifier is complete and correct.",
                "Use the review result to either continue or correct the same activity.",
            ],
        )
    if any(
        word in name
        for word in (
            "fund",
            "budget",
            "cost",
            "disbursement",
            "accountability",
            "payment",
            "reimbursement",
            "netsuite",
        )
    ):
        return (
            "This part of Edify keeps the money trail connected to the work it pays for, so people can see what was requested, approved, paid and accounted for.",
            [
                "Start from the activity or request that needs funding.",
                "Check the amount, status and supporting information before moving forward.",
                "Keep every payment and return reference on the original finance record.",
            ],
        )
    if any(word in name for word in ("school", "cluster", "ssa", "core school")):
        return (
            "This part of Edify helps you use trusted school and assessment information to decide what support is needed.",
            [
                "Confirm the School ID and the selected financial year.",
                "Review the related school, cluster and assessment information together.",
                "Use the findings to guide planning instead of entering a separate note.",
            ],
        )
    if any(
        word in name
        for word in ("target", "analytics", "report", "debrief", "leadership")
    ):
        return (
            "This part of Edify turns live work into a clear picture of progress, gaps and follow-up actions.",
            [
                "Choose the right period and work area first.",
                "Use the linked records to understand why a number changed.",
                "Create or follow up a real action when the information shows a gap.",
            ],
        )
    if any(
        word in name
        for word in (
            "leave",
            "performance",
            "development",
            "user",
            "account",
            "role",
            "system health",
            "audit",
        )
    ):
        return (
            "This part of Edify keeps people, access and support work organised so the right person can act safely and on time.",
            [
                "Use the record that belongs to the person or request.",
                "Give clear details that the next reviewer can understand.",
                "Follow the status and return reason instead of starting another request.",
            ],
        )
    return (
        f"{title} helps you complete one clear part of the Edify workflow and keep the work connected to the right record.",
        [
            "Start from the record named in this guide.",
            "Use the action that Edify makes available for the current status.",
            "Check the status after saving so you know what happens next.",
        ],
    )


def build_learning_sections(
    *,
    title: str,
    category: str,
    roles: list[str],
    purpose: str,
    steps: list[str],
    statuses: list[str] | None = None,
    next_actor: str = "the next authorised workflow owner",
) -> list[dict]:
    """Create a detailed, plain-language lesson for a published Help article."""
    lesson = CATEGORY_LESSONS.get(category, CATEGORY_LESSONS["Getting Started"])
    specific_body, specific_items = _specific_lesson(title, category)
    return [
        section(
            "Who can use this guide",
            "This guide is available to these roles: " + ", ".join(roles) + ".",
        ),
        section("What this guide will help you do", purpose),
        section("How this part of Edify works", specific_body, specific_items),
        section(
            "What you will see and use on the page",
            lesson["explainer"],
            lesson["screen"],
        ),
        section(
            "Before you begin",
            "Make sure you are using the right role and looking at the right record. Edify only shows actions that are available to you.",
        ),
        section(
            "Step-by-step",
            "Follow these steps in order. Each one keeps the work connected to the right record.",
            steps,
        ),
        section("What Edify checks for you", lesson["checks"]),
        section("How this connects to the rest of Edify", lesson["connection"]),
        section(
            "What happens after you submit",
            f"If somebody else needs to check, approve, verify or pay the record, Edify sends it to {next_actor}.",
        ),
        section(
            "Statuses and what they mean",
            "The status tells you where the record is and what needs to happen next. Read the words beside the status; do not rely on colour alone.",
            statuses or [],
        ),
        section(
            "If something is returned or blocked",
            "Open the same record. Read the reason shown on screen, fix only that problem, then use the available submit or resubmit button. Do not make a second record to work around the problem.",
        ),
        section(
            "Tips for getting this right",
            "These simple habits help you avoid delays and make it easier for the next person to continue the work.",
            lesson["tips"],
        ),
        section(
            "How this guide stays correct",
            "Before this guide is published or changed, the Edify team checks it against the live way the system works.",
        ),
    ]
