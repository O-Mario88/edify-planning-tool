/**
 * The photo panel beside the form on a wide screen, as the web draws it
 * (.login-brand in static/css/login.css): the classroom photo under two
 * shades and two fields of dots, the lockup, "Welcome back to Edify Planning
 * & Monitoring", what the platform is for, and the four figures.
 */
import { ImageBackground, StyleSheet, Text, View } from 'react-native';
import Svg, { Circle, Defs, LinearGradient, Mask, Pattern, Rect, Stop } from 'react-native-svg';

import { fonts } from '../../theme';
import { EdifyLogo } from '../../ui/EdifyLogo';
import { type Figures, SignInFigures } from './SignInFigures';
import { OutcomesIcon, PlanIcon, ShieldCheck, TrackIcon } from './signInIcons';
import { BRAND_GRID_BELOW, gradients, panel, shadows } from './signInLook';

const PHOTO = require('../../../assets/brand/login-classroom-portrait.jpg');

const IMPACT = [
  { title: 'Plan with clarity', copy: 'Align activities, budgets,\nand targets with\nconfidence.', Icon: PlanIcon },
  { title: 'Track in real time', copy: 'Monitor visits, tasks,\nand outcomes from\nthe field.', Icon: TrackIcon },
  { title: 'Improve outcomes', copy: 'Use data insights to\ndrive decisions that\nimprove learning.', Icon: OutcomesIcon },
  { title: 'Ensure accountability', copy: 'Promote transparency\nand performance\nat every level.', Icon: ShieldCheck },
] as const;

interface BrandPanelProps {
  readonly width: number;
  readonly height: number;
  readonly contentWidth: number;
  readonly isShort: boolean;
  readonly sizes: { readonly label: number; readonly micro: number; readonly brandTitle: number };
  readonly figures: Figures | null;
}

export function BrandPanel({ width, height, contentWidth, isShort, sizes, figures }: BrandPanelProps) {
  const isNarrow = contentWidth <= BRAND_GRID_BELOW;
  const isVeryShort = height <= 704;
  const title = isShort ? 44 : sizes.brandTitle;
  const iconTile = isShort ? 33.6 : 42.4;
  return (
    <View style={[styles.brand, { width, minHeight: height }]} accessibilityLabel="About Edify Planning and Monitoring">
      <ImageBackground source={PHOTO} resizeMode="cover" style={StyleSheet.absoluteFill} imageStyle={styles.photo} />
      <View style={[StyleSheet.absoluteFill, { backgroundImage: gradients.shadeAcross }]} />
      <View style={[StyleSheet.absoluteFill, { backgroundImage: gradients.shadeDown }]} />
      <Dots style={styles.dotsTop} width={256} height={224} opacity={0.18} />
      <Dots style={styles.dotsMiddle} width={176} height={160} opacity={0.11} />

      <View style={[styles.content, { minHeight: height, paddingTop: isVeryShort ? 32 : 44, paddingBottom: isVeryShort ? 20 : 28 }]}>
        <View style={styles.header}>
          <EdifyLogo height={112 * (123 / 300)} color="white" />
          <View style={styles.headerRule} />
          <Text style={[styles.product, { fontSize: sizes.label, lineHeight: sizes.label * 1.23 }]}>Planning &{'\n'}Monitoring</Text>
        </View>

        <View style={styles.story}>
          <Text style={[styles.eyebrow, { fontSize: isShort ? sizes.micro : sizes.label, lineHeight: (isShort ? sizes.micro : sizes.label) * 1.5, marginBottom: isShort ? 7.2 : 13.6 }]}>
            Welcome back to
          </Text>
          <Text style={[styles.title, { fontSize: title, lineHeight: title * 0.99 }]} accessibilityRole="header">
            Edify Planning &{'\n'}Monitoring
          </Text>
          <View style={[styles.rule, isShort ? styles.ruleShort : null]} />
          <Text style={[styles.summary, isShort ? { fontSize: sizes.label, lineHeight: sizes.label * 1.42 } : null]}>
            Plan smarter. Track field work. Drive accountability.{'\n'}Together, we’re building stronger schools{'\n'}and better futures.
          </Text>
        </View>

        <View style={[styles.impact, isShort ? styles.impactShort : null]}>
          <Text style={[styles.impactTitle, isShort ? { fontSize: sizes.label, marginBottom: 8.8 } : null]} accessibilityRole="header">
            Built for impact. Designed for results.
          </Text>
          <View style={styles.impactGrid}>
            {IMPACT.map(({ title: heading, copy, Icon }, index) => {
              const isLeft = isNarrow ? index % 2 === 0 : index === 0;
              const isRight = isNarrow ? index % 2 === 1 : index === IMPACT.length - 1;
              return (
                <View
                  key={heading}
                  style={[
                    styles.impactItem,
                    isNarrow ? styles.impactItemHalf : styles.impactItemQuarter,
                    isLeft ? styles.impactFirst : styles.impactDivided,
                    isRight ? styles.impactLast : null,
                    isNarrow ? styles.impactItemNarrow : null,
                    isNarrow && index >= 2 ? styles.impactSecondRow : null,
                  ]}
                >
                  <View style={[styles.impactIcon, { width: iconTile, height: iconTile, marginBottom: isShort ? 4.8 : 8.32 }]}>
                    <Icon size={isShort ? 18.4 : 23.2} color="#70cbf8" strokeWidth={1.65} />
                  </View>
                  <Text style={[styles.impactHeading, { fontSize: isShort ? sizes.micro : sizes.label, lineHeight: (isShort ? sizes.micro : sizes.label) * 1.3 }]}>{heading}</Text>
                  {isShort ? null : <Text style={[styles.impactCopy, { fontSize: sizes.micro, lineHeight: sizes.micro * 1.52 }]}>{copy}</Text>}
                </View>
              );
            })}
          </View>
        </View>

        {figures ? (
          <View style={styles.figures}>
            <SignInFigures figures={figures} layout="row" micro={sizes.micro} />
          </View>
        ) : null}
      </View>
    </View>
  );
}

/** A field of dots fading at its ends (.login-brand__dots). */
function Dots({ style, width, height, opacity }: { readonly style: object; readonly width: number; readonly height: number; readonly opacity: number }) {
  return (
    <Svg width={width} height={height} style={[styles.dots, style, { opacity }]} pointerEvents="none">
      <Defs>
        <Pattern id="dot" width={11} height={11} patternUnits="userSpaceOnUse">
          <Circle cx={5.5} cy={5.5} r={1.7} fill="#4fa6dc" />
        </Pattern>
        <LinearGradient id="fade" x1="0" y1="0.18" x2="1" y2="0.82">
          <Stop offset="0" stopColor="#fff" stopOpacity={0} />
          <Stop offset="0.28" stopColor="#fff" stopOpacity={1} />
          <Stop offset="0.72" stopColor="#fff" stopOpacity={1} />
          <Stop offset="1" stopColor="#fff" stopOpacity={0} />
        </LinearGradient>
        <Mask id="fadeMask">
          <Rect width={width} height={height} fill="url(#fade)" />
        </Mask>
      </Defs>
      <Rect width={width} height={height} fill="url(#dot)" mask="url(#fadeMask)" />
    </Svg>
  );
}

const styles = StyleSheet.create({
  brand: { position: 'relative', overflow: 'hidden', backgroundColor: '#001d39' },
  photo: { filter: 'saturate(0.88) contrast(1.04)' },
  dots: { position: 'absolute' },
  dotsTop: { top: 35.2, right: 40 },
  dotsMiddle: { top: 264, right: 80 },
  content: { flex: 1, paddingHorizontal: 48 },
  header: { flexDirection: 'row', alignItems: 'center', minHeight: 44, paddingVertical: 4 },
  headerRule: { width: 1, height: 36, marginLeft: 7.2, marginRight: 11.52, backgroundColor: 'rgba(184, 220, 246, 0.62)' },
  product: { fontFamily: fonts.medium, color: '#b9d4e9' },
  story: { marginTop: 'auto', paddingHorizontal: 9.6 },
  eyebrow: { fontFamily: fonts.semibold, color: '#77cff8', textTransform: 'uppercase' },
  title: {
    fontFamily: fonts.bold,
    color: '#83d3ff',
    textShadowColor: 'rgba(0, 28, 57, 0.42)',
    textShadowOffset: { width: 0, height: 2 },
    textShadowRadius: 22,
  },
  rule: { width: 80, height: 3, marginTop: 28, marginBottom: 18.4, borderRadius: 9999, backgroundColor: '#70cffc' },
  ruleShort: { width: 64, marginTop: 14.4, marginBottom: 10.4 },
  summary: { fontFamily: fonts.medium, fontSize: 16.8, lineHeight: 26.54, color: '#edf7ff' },
  impact: {
    marginTop: 22.4,
    paddingVertical: 18.4,
    paddingHorizontal: 21.6,
    borderWidth: 1,
    borderColor: panel.border,
    borderRadius: 12,
    backgroundImage: gradients.panel,
    boxShadow: shadows.impact,
  },
  impactShort: { marginTop: 11.2, paddingVertical: 11.2, paddingHorizontal: 16 },
  impactTitle: { fontFamily: 'Geist_700Bold_Italic', fontSize: 15.68, lineHeight: 20.38, color: '#ffffff', marginBottom: 15.2 },
  impactGrid: { flexDirection: 'row', flexWrap: 'wrap' },
  impactItem: { minWidth: 0, paddingHorizontal: 15.2 },
  impactItemQuarter: { width: '25%' },
  impactItemHalf: { width: '50%' },
  impactItemNarrow: { paddingVertical: 13.6 },
  impactSecondRow: { borderTopWidth: 1, borderTopColor: panel.impactDivider },
  impactFirst: { paddingLeft: 0 },
  impactDivided: { borderLeftWidth: 1, borderLeftColor: panel.impactDivider },
  impactLast: { paddingRight: 0 },
  impactIcon: {
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: 'rgba(101, 196, 242, 0.48)',
    borderRadius: 10,
    backgroundColor: 'rgba(2, 47, 82, 0.45)',
  },
  impactHeading: { fontFamily: fonts.bold, color: '#ffffff', marginBottom: 3.52 },
  impactCopy: { fontFamily: fonts.medium, color: '#b9d2e5' },
  figures: { marginTop: 16 },
});
