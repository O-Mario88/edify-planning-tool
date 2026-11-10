import { Image } from 'react-native';

// The web app's own mark (static/images/logo.png, 300 x 123), which is white
// on transparent and coloured by CSS there. The app ships it in the two
// colours it is drawn in, so it looks the same on iOS, Android and web.
const sources = {
  navy: require('../../assets/edify-logo-navy.png'),
  white: require('../../assets/edify-logo-white.png'),
} as const;
const ASPECT = 300 / 123;

export type LogoColor = keyof typeof sources;

interface EdifyLogoProps {
  readonly height: number;
  readonly color: LogoColor;
}

export function EdifyLogo({ height, color }: EdifyLogoProps) {
  return (
    <Image
      source={sources[color]}
      accessibilityRole="image"
      accessibilityLabel="Edify"
      resizeMode="contain"
      style={{ height, width: height * ASPECT }}
    />
  );
}
