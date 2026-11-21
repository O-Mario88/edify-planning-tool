import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';

import { SignInService } from '@/gen/edify/identity/v1/sign_in_pb';
import { gatewayClient } from '@/lib/gateway';
import { ACCESS_COOKIE, safeNext } from '@/lib/session';
import { signInMessage } from '@/lib/signInErrors';

/*
 * The sign-in page, as the existing web draws it (templates/layouts/login.html,
 * pages/auth/login.html): the classroom hero with the four figures on the
 * left, the sign-in card on the right. Always light, as there.
 */
type Search = Promise<Record<string, string | string[] | undefined>>;

const first = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);

const PROMISES = [
  ['Plan with clarity', 'Align activities, budgets, and targets with confidence.'],
  ['Track in real time', 'Monitor visits, tasks, and outcomes from the field.'],
  ['Improve outcomes', 'Use data insights to drive decisions that improve learning.'],
  ['Ensure accountability', 'Promote transparency and performance at every level.'],
] as const;

async function figures() {
  try {
    const answer = await gatewayClient(SignInService).getSignInFigures({});
    if (!answer.portfolio) return null;
    return [
      ['Schools reached', answer.schoolsReached, 'Operating schools'],
      ['Schools visited', answer.schoolsVisited, `of ${answer.portfolio}`],
      ['Schools trained', answer.schoolsTrained, `of ${answer.portfolio}`],
      ['SSA completed', answer.ssaCompleted, `of ${answer.portfolio}`],
    ] as const;
  } catch {
    return null;
  }
}

function Field({ label, ...input }: { label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block">
      <span className="mb-2 block text-[0.875rem] font-semibold text-[#17232b]">{label}</span>
      <input
        {...input}
        className="h-[50px] w-full rounded-[10px] border border-[#c7d1d7] bg-[#f8fafb] px-4 text-[0.9375rem] text-[#17232b] outline-none focus:border-[#0e5da3] focus:ring-4 focus:ring-[rgba(14,93,163,0.18)]"
      />
    </label>
  );
}

export default async function LoginPage({ searchParams }: { searchParams: Search }) {
  const params = await searchParams;
  const next = safeNext(first(params.next));
  if ((await cookies()).get(ACCESS_COOKIE)?.value) redirect(next);
  const codeStep = first(params.step) === 'code';
  const error = signInMessage(first(params.error));
  const stats = await figures();

  return (
    <div className="light grid min-h-full bg-[#e7f4fc] lg:grid-cols-[770fr_670fr]">
      <section
        className="relative hidden flex-col justify-between overflow-hidden bg-[#001d39] bg-cover bg-center px-12 py-12 text-white lg:flex"
        style={{
          backgroundImage:
            'linear-gradient(180deg, rgba(0,29,57,0.82), rgba(6,40,71,0.86) 55%, rgba(10,77,134,0.9)), url(/static/images/login-classroom-portrait.jpg)',
        }}
      >
        <div className="flex items-center gap-3">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/static/images/logo.png" alt="Edify" width={110} height={45} className="h-auto w-[110px]" />
          <span className="h-[42px] w-px bg-[rgba(189,216,233,0.72)]" aria-hidden="true" />
          <span className="text-[0.9375rem] leading-[1.35] text-[rgba(215,230,239,0.88)]">
            Planning &amp;
            <br />
            Monitoring
          </span>
        </div>
        <div className="max-w-[540px]">
          <p className="text-[0.875rem] font-semibold uppercase tracking-[0.02em] text-[#8fd0f7]">Welcome back to</p>
          <h1 className="mt-3 text-[3.5rem] font-bold leading-[1.02] tracking-[-0.02em] text-[#8fd0f7]">
            Edify Planning &amp; Monitoring
          </h1>
          <span className="mt-7 block h-[3px] w-20 rounded-full bg-[#8fd0f7]" aria-hidden="true" />
          <p className="mt-7 text-[1.0625rem] leading-[1.6] text-white/90">
            Plan smarter. Track field work. Drive accountability. Together, we’re building stronger schools and better futures.
          </p>
        </div>
        <div className="space-y-4">
          <div className="rounded-[12px] border border-white/15 bg-[rgba(14,58,99,0.72)] p-5">
            <p className="text-[0.9375rem] font-semibold italic">Built for impact. Designed for results.</p>
            <ul className="mt-4 grid grid-cols-4 divide-x divide-white/15">
              {PROMISES.map(([title, body]) => (
                <li key={title} className="px-4 first:pl-0">
                  <p className="text-[0.875rem] font-semibold">{title}</p>
                  <p className="mt-1 text-[0.8125rem] leading-[1.5] text-white/75">{body}</p>
                </li>
              ))}
            </ul>
          </div>
          {stats ? (
            <dl className="grid grid-cols-4 divide-x divide-white/15 rounded-[12px] border border-white/15 bg-[rgba(14,58,99,0.72)] p-4">
              {stats.map(([label, value, note]) => (
                <div key={label} className="px-4 first:pl-0">
                  <dt className="text-[0.8125rem] font-semibold">{label}</dt>
                  <dd className="mt-1 text-[1.375rem] font-bold">{value}</dd>
                  <dd className="text-[0.8125rem] text-white/75">{note}</dd>
                </div>
              ))}
            </dl>
          ) : null}
        </div>
      </section>

      <section className="flex items-center justify-center bg-[linear-gradient(135deg,#eef7fd,#e4f2fb)] px-4 py-10">
        <div className="w-full max-w-[462px] rounded-[16px] border border-[#d9e3ed] bg-white px-11 py-11 shadow-[0_24px_60px_-30px_rgba(18,74,112,0.35)]">
          <div className="text-center">
            <span
              role="img"
              aria-label="Edify"
              className="mx-auto block h-[47px] w-[114px] bg-[#0b4a82] [mask-image:url(/static/images/logo.png)] [mask-repeat:no-repeat] [mask-size:contain] [mask-position:center]"
            />
            <h2 className="mt-5 text-[1.5rem] font-bold text-[#17232b]">{codeStep ? 'Enter your code' : 'Sign in'}</h2>
            <p className="mt-2 text-[0.9375rem] text-[#4d6170]">
              {codeStep ? 'We sent a sign-in code to you. Enter it to continue.' : 'Welcome back to your planning workspace.'}
            </p>
          </div>
          {error ? (
            <p role="alert" className="mt-6 rounded-[10px] border border-[#fecdd3] bg-[#fff1f2] px-4 py-3 text-[0.875rem] font-semibold text-[#9f1239]">
              {error}
            </p>
          ) : null}
          {codeStep ? (
            <form method="post" action="/auth/verify-code" className="mt-8 space-y-6">
              <input type="hidden" name="next" value={next} />
              <Field label="Sign-in code" name="code" inputMode="numeric" autoComplete="one-time-code" required autoFocus />
              <button type="submit" className="h-14 w-full rounded-[10px] bg-[#0b55a0] text-[1rem] font-semibold text-white shadow-[0_10px_24px_-14px_rgba(11,85,160,0.9)] hover:bg-[#0a4d86]">
                Verify and continue
              </button>
            </form>
          ) : (
            <form method="post" action="/auth/sign-in" className="mt-8 space-y-6">
              <input type="hidden" name="next" value={next} />
              <Field label="Email address" name="email" type="email" autoComplete="username" required />
              <Field label="Password" id="current-password" name="password" type="password" autoComplete="current-password" required />
              <button type="submit" className="h-14 w-full rounded-[10px] bg-[#0b55a0] text-[1rem] font-semibold text-white shadow-[0_10px_24px_-14px_rgba(11,85,160,0.9)] hover:bg-[#0a4d86]">
                Access workspace
              </button>
            </form>
          )}
          <div className="mt-6 flex items-start gap-4 border-t border-[#e3e9ee] pt-6">
            <span className="grid h-12 w-12 shrink-0 place-items-center rounded-[10px] bg-white text-[#0e5da3] shadow-[0_6px_18px_-8px_rgba(18,74,112,0.35)]" aria-hidden="true">
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.8}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 3l7 3v6c0 4.5-3 7.7-7 9-4-1.3-7-4.5-7-9V6l7-3z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4" />
              </svg>
            </span>
            <div>
              <p className="text-[0.9375rem] font-semibold text-[#17232b]">Secure access</p>
              <p className="text-[0.8125rem] text-[#4d6170]">Your data is encrypted and protected by enterprise-grade security.</p>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
