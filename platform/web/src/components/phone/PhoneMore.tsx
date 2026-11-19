/*
 * The menu behind "More", as the native app draws it (mobile/src/screens/
 * MoreScreen.tsx MenuScreen): the reader's account, the roles they can work
 * as, then their own menu section by section (an icon, the page's name and a
 * chevron on each row), and Sign out. The rows are the reader's sidebar, as
 * the gateway gives it for their role.
 */
import './phone.css';

import { Check, ChevronRight, LogOut } from 'lucide-react';
import Link from 'next/link';

import type { NavSection } from '@/gen/edify/screens/v1/navigation_pb';
import { safeIcon } from '@/lib/icon';

import { LeaveOnDesktop } from './LeaveOnDesktop';

export interface PhoneMoreProps {
  readonly name: string;
  readonly email: string;
  readonly activeRole: string;
  readonly roles: readonly string[];
  readonly sections: readonly NavSection[];
}

export function PhoneMore({ name, email, activeRole, roles, sections }: PhoneMoreProps) {
  return (
    <div data-ph="page" data-page="/more">
      <LeaveOnDesktop />
      <section data-ph="more-account" aria-label="Your account">
        <p data-ph="more-name">{name}</p>
        <p data-ph="more-meta">{[activeRole, email].filter(Boolean).join(' · ')}</p>
      </section>

      {roles.length > 1 ? (
        <section data-ph="more-section" aria-label="Work as">
          <h2 data-ph="more-label">Work as</h2>
          <div data-ph="more-group">
            {roles.map((role) =>
              role === activeRole ? (
                <span key={role} data-ph="more-row" aria-current="true">
                  <span data-ph="more-row-label">{role}</span>
                  <Check size={18} aria-label="current" data-ph="more-check" />
                </span>
              ) : (
                <form key={role} method="post" action="/auth/switch-role" data-ph="more-form">
                  <input type="hidden" name="role" value={role} />
                  <button type="submit" data-ph="more-row" aria-label={`Work as ${role}`}>
                    <span data-ph="more-row-label">{role}</span>
                  </button>
                </form>
              ),
            )}
          </div>
        </section>
      ) : null}

      {sections
        .filter((section) => section.items.length > 0)
        .map((section) => (
          <section key={section.label} data-ph="more-section" aria-label={section.label || 'Menu'}>
            {section.label ? <h2 data-ph="more-label">{section.label}</h2> : null}
            <div data-ph="more-group">
              {section.items.map((item) => (
                <Link key={`${item.url}-${item.label}`} href={item.url} data-ph="more-row">
                  <span data-ph="more-icon" aria-hidden="true" dangerouslySetInnerHTML={{ __html: safeIcon(item.iconSvg) }} />
                  <span data-ph="more-row-label">{item.label}</span>
                  <ChevronRight size={16} aria-hidden="true" data-ph="more-chevron" />
                </Link>
              ))}
            </div>
          </section>
        ))}

      <form method="post" action="/auth/sign-out" data-ph="more-form">
        <button type="submit" data-ph="more-signout">
          <LogOut size={18} aria-hidden="true" />
          Sign out
        </button>
      </form>
    </div>
  );
}
