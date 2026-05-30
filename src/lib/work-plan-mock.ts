// Mobile Work Plan — staff personal monthly view.
//
// Designed for the CCEO / Country Program Lead to track their own monthly
// focus, key targets, tasks, upcoming activities, and recent wins. Uses
// the same verified-only contract as the rest of the app: counts come
// from the verified leaderboard / target engines so the mobile and
// desktop dashboards stay self-consistent.

export type TaskStatus = "Completed" | "In Progress" | "Overdue" | "Not Started";
export type Priority = "High" | "Medium" | "Low";

export type WorkPlanHeader = {
  title: string;
  month: string;
  notificationCount: number;
  user: { name: string; initials: string; avatar?: string };
};

export const workPlanHeader: WorkPlanHeader = {
  title: "My Monthly Work Plan",
  month: "May 2025",
  notificationCount: 8,
  user: { name: "Daniel Mwangi", initials: "DM" },
};

// Monthly progress overview ring + counts
export const monthlyProgress = {
  overallPercent: 78,
  total: 32,
  completed: 25,
  inProgress: 5,
  overdue: 2,
  status: "On Track" as const,
  message: "Keep up the great work!",
};

// Focus banner (dark navy)
export const focusThisMonth = {
  title: "Advance Core School support and improve SSA performance across all districts.",
  priority: "High" as Priority,
  dueDate: "May 31, 2025",
};

// Key Targets — 4 mini ring tiles
export type KeyTarget = {
  key: string;
  label: string;
  current: number;
  total: number;
  percent: number;
  color: "emerald" | "blue" | "orange" | "violet";
  icon: "school" | "clipboard" | "userCheck" | "users";
};

export const keyTargets: KeyTarget[] = [
  { key: "core",      label: "Core Schools",     current: 128, total: 150, percent: 85, color: "emerald", icon: "school"    },
  { key: "ssa",       label: "SSA Assessments",  current: 95,  total: 120, percent: 79, color: "blue",    icon: "clipboard" },
  { key: "visits",    label: "Visits",           current: 64,  total: 80,  percent: 80, color: "orange",  icon: "userCheck" },
  { key: "trainings", label: "Trainings",        current: 56,  total: 70,  percent: 80, color: "violet",  icon: "users"     },
];

// Tasks — used by the tabbed list
export type WorkTask = {
  id: string;
  title: string;
  priority: Priority;
  dueDate: string; // "May 5, 2025"
  status: TaskStatus;
};

export const myTasks: WorkTask[] = [
  { id: "T-1", title: "Conduct SSA for 8 Core Schools",          priority: "High",   dueDate: "May 5, 2025",  status: "Completed"  },
  { id: "T-2", title: "Follow Up visits for 10 Core Schools",    priority: "Medium", dueDate: "May 10, 2025", status: "In Progress" },
  { id: "T-3", title: "Deliver Training: Leadership Best Practice", priority: "High", dueDate: "May 15, 2025", status: "In Progress" },
  { id: "T-4", title: "Verify Salesforce records & evidence",    priority: "High",   dueDate: "May 12, 2025", status: "Overdue"    },
  { id: "T-5", title: "Submit weekly debrief for Cluster 4",     priority: "Medium", dueDate: "May 17, 2025", status: "In Progress" },
  { id: "T-6", title: "Cluster training prep — May cohort",      priority: "High",   dueDate: "May 18, 2025", status: "Not Started" },
];

// Tab counts derived from myTasks
export type TaskTabKey = "all" | "completed" | "in_progress" | "overdue";

export function taskTabCounts() {
  return {
    all:         myTasks.length,
    completed:   myTasks.filter((t) => t.status === "Completed").length,
    in_progress: myTasks.filter((t) => t.status === "In Progress").length,
    overdue:     myTasks.filter((t) => t.status === "Overdue").length,
  };
}

// Upcoming activities
export type UpcomingActivity = {
  id: string;
  monthShort: string;
  day: string;
  title: string;
  location: string;
  time: string;
  status: "Upcoming" | "Today" | "Tomorrow";
};

export const upcomingActivities: UpcomingActivity[] = [
  { id: "U-1", monthShort: "MAY", day: "12", title: "Core School Visit", location: "New Hope Academy",   time: "10:00 AM", status: "Upcoming" },
  { id: "U-2", monthShort: "MAY", day: "15", title: "Cluster Training",   location: "Mukono Cluster Hub", time: "09:30 AM", status: "Upcoming" },
  { id: "U-3", monthShort: "MAY", day: "18", title: "Partner Check-in",   location: "Virtual",            time: "02:00 PM", status: "Upcoming" },
];

// Recent achievements
export type RecentAchievement = {
  id: string;
  title: string;
  body: string;
  date: string; // "May 3, 2025"
};

export const recentAchievements: RecentAchievement[] = [
  {
    id: "A-1",
    title: "SSA Completion Milestone",
    body: "You completed SSA for 8 Core Schools this month.",
    date: "May 3, 2025",
  },
  {
    id: "A-2",
    title: "Verified Impact Leader",
    body: "Top of the verified leaderboard for Valid Visits this week.",
    date: "Apr 28, 2025",
  },
];
