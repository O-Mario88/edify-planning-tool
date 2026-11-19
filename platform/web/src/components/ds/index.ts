/**
 * The web app's design system: the live system's own design, as components.
 * Every page is built from these, and each draws the existing web's markup
 * and class names, so the existing stylesheets (linked by the root layout)
 * set it exactly as on the live pages.
 *
 *   Layout      the page frame (FeedPage, the page's own pageClass), group
 *               layouts (PageBlock.group), sections (SectionHeading)
 *   Typography  Eyebrow, PageTitle, SectionHeading, CardTitle, Caption
 *   Header      PageHeader with its buttons (BUTTON_PRIMARY / BUTTON_OUTLINE)
 *   Cards       StandardCard (the registered card), Card (a plain surface)
 *   Tiles       the figure row (KpiStrip / FeedStrip: context-metrics),
 *               MiniTile (a small toned figure)
 *   Graphs      FeedChart (to follow static/js/chart-standard.js exactly)
 *   Data        FeedTable, Pager, TabRail, FeedChips, FilterBar, Badge,
 *               RowActions, Meter, the empty state (inside FeedTable)
 *
 * The catalogue at /design-system shows each of them.
 */
export { Badge, badgeTone } from '../blocks/Badge';
export { BUTTON_OUTLINE, BUTTON_PRIMARY } from '../blocks/buttons';
export { Card } from '../blocks/Card';
export { FilterBar } from '../blocks/FilterBar';
export type { Filter, FilterOption } from '../blocks/FilterBar';
export { KpiStrip } from '../blocks/KpiStrip';
export { PageHeader } from '../blocks/PageHeader';
export { Pager } from '../blocks/Pager';
export { RowActions } from '../blocks/RowActions';
export { TabRail } from '../blocks/TabRail';
export { FeedChart } from '../page/FeedChart';
export { FeedChips } from '../page/FeedChips';
export { FeedTable } from '../page/FeedTable';
export { Meter, MiniTile } from './Meter';
export { StandardCard } from './StandardCard';
export type { CardLink } from './StandardCard';
export { Caption, CardTitle, Eyebrow, PageTitle, SectionHeading } from './Typography';
