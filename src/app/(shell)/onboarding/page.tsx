import Link from "next/link";
import {
  Sparkles,
  CheckCircle2,
  ClipboardList,
  Building2,
  ShieldCheck,
  Users,
  ArrowRight,
} from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { getCurrentUser, ROLE_REDIRECT } from "@/lib/auth";

export default async function OnboardingPage() {
  const user = await getCurrentUser();
  const dashHref = ROLE_REDIRECT[user.role];

  return (
    <StubPage
      title={`Welcome, ${user.name.split(" ")[0]} 👋`}
      subtitle="Five quick stops to find your way around Edify. Skip whenever you're ready — your dashboard is one tap away."
    >
      <section className="card p-3.5 space-y-3 bg-[var(--color-edify-soft)]/40">
        <div className="flex items-start gap-3">
          <span className="h-9 w-9 rounded-md bg-[var(--color-edify-primary)] text-white grid place-items-center shrink-0">
            <Sparkles size={16} />
          </span>
          <div className="min-w-0">
            <h2 className="text-[15px] font-extrabold tracking-tight">Your role: {user.role.replace(/([A-Z])/g, " $1").trim()}</h2>
            <p className="text-[12px] muted">
              Edify routes you to <span className="font-semibold text-[var(--color-edify-text)]">{dashHref}</span>{" "}
              by default — that&apos;s the dashboard built for your day.
            </p>
          </div>
          <Link
            href={dashHref}
            className="h-9 px-3.5 rounded-xl bg-[var(--color-edify-primary)] text-white text-body font-semibold inline-flex items-center gap-1.5"
          >
            Go to dashboard
            <ArrowRight size={12} />
          </Link>
        </div>
      </section>

      <Step
        n={1}
        title="Plan your week"
        body="Tap the green + on the bottom nav (mobile) or open Planning Tool (desktop). High-priority schools are pre-ranked for you."
        cta="Open Planning"
        href="/planning"
        Icon={ClipboardList}
      />
      <Step
        n={2}
        title="Submit a Daily Field Debrief"
        body="Six honest questions at the end of each field day. Pattern detection rolls them up into leadership decisions."
        cta="Open Debrief"
        href="/field-intelligence"
        Icon={Sparkles}
      />
      <Step
        n={3}
        title="Check your school directory"
        body="The schools you see are the ones Salesforce assigns to you. Click any school for its 360°."
        cta="Open Schools"
        href="/schools"
        Icon={Building2}
      />
      <Step
        n={4}
        title="Understand verified work"
        body="Only Salesforce-verified work counts toward targets and the leaderboard. The Help center has the full rule set."
        cta="Read the rules"
        href="/help/valid-visit"
        Icon={ShieldCheck}
      />
      <Step
        n={5}
        title="Find your team"
        body="Country Program Lead, Country Director, supervisor — they're all linkable from your Profile."
        cta="Open Profile"
        href="/profile"
        Icon={Users}
      />
    </StubPage>
  );
}

function Step({
  n,
  title,
  body,
  cta,
  href,
  Icon,
}: {
  n: number;
  title: string;
  body: string;
  cta: string;
  href: string;
  Icon: typeof CheckCircle2;
}) {
  return (
    <section className="card p-3.5 flex items-start gap-3">
      <span className="h-10 w-10 rounded-xl bg-emerald-100 text-emerald-700 grid place-items-center shrink-0 text-body-lg font-extrabold">
        {n}
      </span>
      <div className="flex-1 min-w-0">
        <h3 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-1.5">
          <Icon size={13} className="text-[var(--color-edify-muted)]" />
          {title}
        </h3>
        <p className="text-[11.5px] muted mt-0.5 leading-snug">{body}</p>
      </div>
      <Link
        href={href}
        className="h-9 px-3 rounded-xl border border-[var(--color-edify-border)] text-[12px] font-semibold inline-flex items-center gap-1.5 hover:bg-[var(--color-edify-soft)]/60"
      >
        {cta}
        <ArrowRight size={12} />
      </Link>
    </section>
  );
}
