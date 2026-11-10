import { SvgXml } from 'react-native-svg';

interface SvgIconProps {
  /** SVG markup from the server: the same drawing the web page uses. */
  readonly xml: string;
  readonly size: number;
  readonly color: string;
}

const DEFAULT_STROKE = 'stroke-width="1.8"';
const HTML_ONLY_ATTRIBUTES = /\s(?:class|aria-hidden|focusable)="[^"]*"/g;

/**
 * Draws one of the web app's own icons. The markup comes from the existing
 * application's templates through the screen feed, so an icon here is the
 * icon there. Icons that take their stroke width from the web's stylesheet
 * are given it here.
 */
export function SvgIcon({ xml, size, color }: SvgIconProps) {
  if (!xml.startsWith('<svg')) {
    return null;
  }
  // Attributes that mean something to a browser's HTML parser only.
  const cleaned = xml.replace(HTML_ONLY_ATTRIBUTES, '');
  const drawing = cleaned.includes('stroke-width')
    ? cleaned
    : cleaned.replace('<svg', `<svg ${DEFAULT_STROKE}`);
  return <SvgXml xml={drawing} width={size} height={size} color={color} />;
}
