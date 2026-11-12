import { badgeClasses } from './tones';

export function Badge({ tone, children, title }: { tone: string; children: React.ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className={`inline-flex items-center whitespace-nowrap rounded-full border px-2 py-px text-[length:var(--edify-text-micro-size)] font-semibold leading-[1.45] ${badgeClasses(tone)}`}
    >
      {children}
    </span>
  );
}
