import { BadgeIcon } from '../shell/icons';
import { badgeClasses } from './tones';

export function Badge({ tone, children, title, icon = '' }: { tone: string; children: React.ReactNode; title?: string; icon?: string }) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-px text-[length:var(--edify-text-micro-size)] font-semibold leading-[1.45] ${badgeClasses(tone)}`}
    >
      {icon ? <BadgeIcon name={icon} /> : null}
      {children}
    </span>
  );
}
