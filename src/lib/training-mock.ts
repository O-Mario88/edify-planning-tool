// Cluster-based training cohorts. Production swaps this for a real
// curriculum + cohort store with sign-up + attendance tracking.
//
// `intervention` corresponds to one of the 8 SSA intervention areas so the
// trainings page can be cross-referenced with SSA improvement data later.

export type TrainingStatus = "Scheduled" | "In Progress" | "Completed" | "Cancelled";

export type Training = {
  id: string;
  title: string;
  intervention: string;
  cluster: string;
  facilitator: string;
  date: string;
  participants: number;
  status: TrainingStatus;
};

export const TRAININGS: Training[] = [
  {
    id: "T-001",
    title: "Leadership Best Practice (Headteachers)",
    intervention: "Leadership Best Practice",
    cluster: "Kitgum Central",
    facilitator: "Daniel Mwangi",
    date: "May 12, 2025",
    participants: 22,
    status: "Scheduled",
  },
  {
    id: "T-002",
    title: "Classroom Practice Refresher",
    intervention: "Teaching Environment",
    cluster: "Mukono",
    facilitator: "Aisha Dar",
    date: "May 14, 2025",
    participants: 31,
    status: "In Progress",
  },
  {
    id: "T-003",
    title: "SSA Follow-Up Coaching",
    intervention: "Leadership Best Practice",
    cluster: "Mbarara West",
    facilitator: "Brian Lumumba",
    date: "May 16, 2025",
    participants: 18,
    status: "In Progress",
  },
  {
    id: "T-004",
    title: "Christ-like Behavior — Year 2",
    intervention: "Christ-like Behavior",
    cluster: "Kampala North",
    facilitator: "Naome Kintu",
    date: "May 8, 2025",
    participants: 28,
    status: "Completed",
  },
  {
    id: "T-005",
    title: "Numeracy Foundations",
    intervention: "Learning Environment",
    cluster: "Pakele",
    facilitator: "James Okello",
    date: "May 5, 2025",
    participants: 24,
    status: "Completed",
  },
  {
    id: "T-006",
    title: "Teaching Environment Audit",
    intervention: "Teaching Environment",
    cluster: "Orom",
    facilitator: "Grace Nansubuga",
    date: "Apr 30, 2025",
    participants: 14,
    status: "Cancelled",
  },
  {
    id: "T-007",
    title: "Fees, Budget & Accounts Workshop",
    intervention: "Fees, Budget & Accounts",
    cluster: "Jinja",
    facilitator: "Peter Wakabi",
    date: "May 20, 2025",
    participants: 19,
    status: "Scheduled",
  },
  {
    id: "T-008",
    title: "Government Requirements Briefing",
    intervention: "Government Requirements",
    cluster: "Mbale",
    facilitator: "Rose Atim",
    date: "Apr 28, 2025",
    participants: 26,
    status: "Completed",
  },
];
