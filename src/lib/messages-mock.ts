// Mock message threads. Shared between /messages (list) and
// /messages/[id] (thread detail).

export type MessageType = "direct" | "announcement" | "team";

export type MessageAuthor = {
  name:     string;
  initials: string;
  role:     string;
};

export type Message = {
  author: "me" | MessageAuthor;
  body:   string;
  at:     string; // human-friendly timestamp
};

export type MessageThread = {
  id:       string;
  with:     string;
  preview:  string;
  ago:      string;
  unread:   number;
  type:     MessageType;
  messages: Message[];
};

const SARAH:   MessageAuthor = { name: "Sarah Okello",   initials: "SO", role: "Country Director" };
const ESTHER:  MessageAuthor = { name: "Esther Wanjiru", initials: "EW", role: "Regional VP"      };
const ANNOUNCE:MessageAuthor = { name: "Edify HQ",       initials: "EH", role: "Announcement"    };
const KITGUM:  MessageAuthor = { name: "Kitgum team",    initials: "KT", role: "Team channel"    };
const DANIEL:  MessageAuthor = { name: "Daniel Mwangi",  initials: "DM", role: "CPL — Western"   };
const ANNE:    MessageAuthor = { name: "Anne Wairimu",   initials: "AW", role: "Human Resource"  };

export const messageThreads: MessageThread[] = [
  {
    id:      "m-1",
    with:    "Sarah Okello (CD)",
    preview: "Please re-cluster the West loop for next month.",
    ago:     "12m",
    unread:  2,
    type:    "direct",
    messages: [
      { author: SARAH, at: "Today · 09:12", body: "Hi — looking at the West loop, three CCEOs are running over capacity. Can you re-cluster for next month?" },
      { author: SARAH, at: "Today · 09:14", body: "Aim for 11–12 schools per cluster max. Daniel's already flagged route difficulty." },
      { author: "me",  at: "Today · 09:30", body: "Will rework today. Sending a proposed split before EOD." },
    ],
  },
  {
    id:      "m-2",
    with:    "Esther Wanjiru (RVP)",
    preview: "Q3 budget is approved. Forward to your CPLs.",
    ago:     "1h",
    unread:  0,
    type:    "direct",
    messages: [
      { author: ESTHER, at: "Today · 08:00", body: "Q3 budget came through. Disbursements unblock Monday." },
      { author: ESTHER, at: "Today · 08:01", body: "Please forward to your CPLs and brief them on the priority schools list." },
      { author: "me",   at: "Today · 08:10", body: "Forwarded. Daniel and Aisha will brief their CCEOs this week." },
    ],
  },
  {
    id:      "m-3",
    with:    "Country-wide Announcement",
    preview: "Annual SSA refresh window opens 1 Oct across all 8 interventions.",
    ago:     "2h",
    unread:  1,
    type:    "announcement",
    messages: [
      { author: ANNOUNCE, at: "Today · 07:00", body: "Annual SSA refresh opens 1 October across all 8 interventions. Refresh window closes 30 November." },
      { author: ANNOUNCE, at: "Today · 07:00", body: "CPLs: please confirm route plans for each CCEO before 25 September so the engine can pre-stage the visits." },
    ],
  },
  {
    id:      "m-4",
    with:    "Kitgum team",
    preview: "Reminder: Cluster Training Batch 5 starts Monday.",
    ago:     "Yesterday",
    unread:  0,
    type:    "team",
    messages: [
      { author: KITGUM, at: "Yesterday · 16:00", body: "Reminder: Cluster Training Batch 5 starts Monday at 09:00. Venue is Holy Rosary Hall." },
      { author: KITGUM, at: "Yesterday · 16:02", body: "Bring printed copies of the new SSA rubric. Lunch will be provided." },
    ],
  },
  {
    id:      "m-5",
    with:    "Daniel Mwangi (CPL)",
    preview: "Forwarded fund request #FR-014. Please review.",
    ago:     "2d",
    unread:  0,
    type:    "direct",
    messages: [
      { author: DANIEL, at: "2 days ago · 11:00", body: "Forwarded fund request #FR-014. Please review when you get a chance — Moses needs the disbursement by Friday." },
      { author: "me",   at: "2 days ago · 14:30", body: "Reviewing now. Will sign off today if receipts are attached." },
    ],
  },
  {
    id:      "m-6",
    with:    "HR — Anne Wairimu",
    preview: "Mid-year support review for Moses T. — schedule call.",
    ago:     "3d",
    unread:  0,
    type:    "direct",
    messages: [
      { author: ANNE,  at: "3 days ago · 10:00", body: "Mid-year support review for Moses T. — can we schedule the call this week? I have time Wed/Thu afternoons." },
      { author: "me",  at: "3 days ago · 11:00", body: "Thu 14:00 works. I'll send the calendar invite." },
    ],
  },
];

export function getThread(id: string): MessageThread | undefined {
  return messageThreads.find((t) => t.id === id);
}
