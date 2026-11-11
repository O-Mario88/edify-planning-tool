/** The web sign-in page's own icons, path for path (templates/layouts/login.html). */
import Svg, { Circle, Path, Rect } from 'react-native-svg';

interface IconProps {
  readonly size: number;
  readonly color: string;
  readonly strokeWidth?: number;
}

function Icon({ size, color, strokeWidth = 1.7, children }: IconProps & { readonly children: React.ReactNode }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      {children}
    </Svg>
  );
}

export function EyeOpen(props: IconProps) {
  return (
    <Icon {...props}>
      <Path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z" />
      <Circle cx="12" cy="12" r="2.6" />
    </Icon>
  );
}

export function EyeClosed(props: IconProps) {
  return (
    <Icon {...props}>
      <Path d="m3 3 18 18M10.6 6.1c.46-.07.93-.1 1.4-.1 6 0 9.5 6 9.5 6a18 18 0 0 1-2.4 3.1M6.5 6.6C3.9 8.3 2.5 12 2.5 12s3.5 6 9.5 6c1.2 0 2.3-.24 3.3-.63M9.9 9.9a3 3 0 0 0 4.2 4.2" />
    </Icon>
  );
}

export function ShieldCheck(props: IconProps) {
  return (
    <Icon {...props}>
      <Path d="M12 22s8-3 8-9V5l-8-3-8 3v8c0 6 8 9 8 9Z" />
      <Path d="m9 12 2 2 4-4" />
    </Icon>
  );
}

export function AlertCircle(props: IconProps) {
  return (
    <Icon {...props}>
      <Circle cx="12" cy="12" r="9" />
      <Path d="M12 7v6M12 17h.01" />
    </Icon>
  );
}

export function PlanIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <Rect x="3" y="5" width="18" height="16" rx="2" />
      <Path d="M16 3v4M8 3v4M3 10h18M8 14h.01M12 14h.01M16 14h.01M8 18h.01M12 18h.01" />
    </Icon>
  );
}

export function TrackIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <Path d="M20 10c0 5-8 11-8 11S4 15 4 10a8 8 0 1 1 16 0Z" />
      <Circle cx="12" cy="10" r="2.5" />
    </Icon>
  );
}

export function OutcomesIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <Path d="M4 20V10M10 20V14M16 20V7M22 20V4" />
      <Path d="m4 7 5-4 5 3 7-5M17 1h4v4" />
    </Icon>
  );
}
