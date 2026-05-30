// Per-role debrief prompts. Single source of truth for the form
// questions so the renderer doesn't drift from the spec.

import type { DebriefSubmitterRole } from "./types";

export type DebriefPrompt = {
  key:         string;
  prompt:      string;
  placeholder: string;
  /** Some prompts are short summaries that fit a single-line input;
   *  most are multi-line textareas. */
  short?:      boolean;
};

// Two universal prompts the spec mandates ("what happened" + "what
// needs attention") plus the supportive opener. Per-role prompts add
// depth without making the form feel like a report.
const CCEO_PROMPTS: DebriefPrompt[] = [
  { key: "happened",        prompt: "What happened in the field today?",                                           placeholder: "Share the field reality — visits, trainings, follow-ups…" },
  { key: "most-important",  prompt: "Which school or activity was most important today?",                          placeholder: "Name the school / activity and why it mattered.", short: true },
  { key: "went-well",       prompt: "What went well?",                                                              placeholder: "Wins, breakthroughs, what worked." },
  { key: "difficult",       prompt: "What was difficult?",                                                          placeholder: "What blocked you, what was hard." },
  { key: "needs-followup",  prompt: "What school support issue needs follow-up?",                                  placeholder: "What does the school need next from us?" },
  { key: "wellbeing",       prompt: "Any workload, travel, safety, or wellbeing concern?",                          placeholder: "Honest answer — leadership uses this to support you." },
  { key: "external-factors", prompt: "Did funds, distance, weather, school availability, or partner delay affect the work?", placeholder: "Note any external factor that shaped today." },
  { key: "support-needed",  prompt: "What support do you need from PL, CD, HR, or Finance?",                       placeholder: "Be specific — what would unblock you tomorrow." },
  { key: "leadership",      prompt: "What should leadership know?",                                                placeholder: "Anything else worth raising." },
];

const PL_PROMPTS: DebriefPrompt[] = [
  { key: "main-reality",      prompt: "What was the main program reality today?",                                  placeholder: "What's the one thing leadership should understand about today?" },
  { key: "attention",         prompt: "Which CCEOs, partners, or schools need attention?",                          placeholder: "Name them and why — keep it factual." },
  { key: "blocking",          prompt: "What is blocking execution?",                                                placeholder: "Funds, planning, partner delivery, evidence flow…" },
  { key: "field-pattern",     prompt: "What field pattern are you noticing?",                                       placeholder: "A recurring barrier, a repeated success — what's the signal?" },
  { key: "staff-overload",    prompt: "Are any staff overloaded or unsupported?",                                   placeholder: "HR uses this to act — be honest, not protective." },
  { key: "partner-delivery",  prompt: "Are any partners struggling or delaying delivery?",                          placeholder: "Name the partner, the activity, the gap." },
  { key: "cd-decision",       prompt: "What decision does CD need to make?",                                        placeholder: "Be explicit — what choice are you escalating?" },
  { key: "hr-support",        prompt: "What support does HR need to provide?",                                      placeholder: "People issues, coaching, escalations." },
  { key: "improvements",      prompt: "What should be improved in planning, funding, partner coordination, or evidence workflow?", placeholder: "Concrete improvement ideas." },
];

const PARTNER_PROMPTS: DebriefPrompt[] = [
  { key: "activity",          prompt: "What activity did you complete today?",                                     placeholder: "Visit, training, follow-up — what was delivered.", short: true },
  { key: "at-school",         prompt: "What happened at the school or cluster?",                                    placeholder: "Describe the reality on the ground." },
  { key: "went-well",         prompt: "What went well?",                                                            placeholder: "Wins to acknowledge." },
  { key: "difficult",         prompt: "What was difficult?",                                                        placeholder: "Honest answer — Edify uses this to improve support." },
  { key: "needed-most",       prompt: "What did the school need most?",                                             placeholder: "Beyond the planned activity — what was the school looking for?" },
  { key: "ssa-relevance",     prompt: "Was the assigned activity relevant to the school's SSA need?",              placeholder: "If not, explain the gap so we can fix the assignment logic." },
  { key: "followup",          prompt: "What follow-up is needed?",                                                  placeholder: "What should CCEO / PL / Edify do next?" },
  { key: "coordination",      prompt: "Were there any coordination issues with Edify staff?",                       placeholder: "Communication, scheduling, evidence handoff — anything to flag." },
  { key: "cceo-pl-should-know", prompt: "What should CCEO or PL know?",                                              placeholder: "School-level facts the assigned CCEO needs." },
  { key: "edify-improve",     prompt: "What can Edify improve to make partner delivery better?",                    placeholder: "Help us serve schools better." },
];

export function promptsForRole(role: DebriefSubmitterRole): DebriefPrompt[] {
  switch (role) {
    case "CCEO":               return CCEO_PROMPTS;
    case "CountryProgramLead": return PL_PROMPTS;
    case "Partner":            return PARTNER_PROMPTS;
  }
}

export function titleForRole(role: DebriefSubmitterRole): string {
  switch (role) {
    case "CCEO":               return "Today's Field Debrief";
    case "CountryProgramLead": return "Today's Program Debrief";
    case "Partner":            return "Today's Partner Debrief";
  }
}

export function subtitleForRole(role: DebriefSubmitterRole): string {
  switch (role) {
    case "CCEO":               return "Tell leadership what really happened in the field today.";
    case "CountryProgramLead": return "Share program realities, team challenges, partner issues, and decisions needed.";
    case "Partner":            return "Share what happened during school support and what Edify should improve.";
  }
}
