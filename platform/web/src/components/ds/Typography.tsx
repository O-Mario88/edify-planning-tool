/*
 * The design system's type scale: the existing web's own classes and size
 * tokens (static/css/design-system.css: display, title, label, micro), so
 * every page sets text the same way the live system does.
 */
import type { ReactNode } from 'react';

/** The small uppercase line over a page title ("SCHOOLS & FIELD"). */
export function Eyebrow({ children }: { children: ReactNode }) {
  return <p className="edify-page-eyebrow">{children}</p>;
}

/** A page's title (display size). */
export function PageTitle({ children }: { children: ReactNode }) {
  return <h1 className="edify-page-title edify-page-header__title">{children}</h1>;
}

/** A heading between a page's sections ("Platform Business Overview"). */
export function SectionHeading({ children, note }: { children: ReactNode; note?: ReactNode }) {
  return (
    <div>
      <h2 className="edify-section-heading">{children}</h2>
      {note ? <p className="edify-text-caption edify-text-muted">{note}</p> : null}
    </div>
  );
}

/** A card's title: 15px semibold, as components/card.html and registered_card.html set it. */
export function CardTitle({ children, id }: { children: ReactNode; id?: string }) {
  return (
    <h3 id={id} className="text-[15px] font-semibold edify-text tracking-tight leading-tight">
      {children}
    </h3>
  );
}

/** Small supporting text (the caption size, muted). */
export function Caption({ children }: { children: ReactNode }) {
  return <p className="edify-text-caption edify-text-muted">{children}</p>;
}
