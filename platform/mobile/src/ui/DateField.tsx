/**
 * The Edify calendar on a date field (static/js/date-picker.js; owner,
 * 2026-09-26: one calendar for every date field, never the system's own
 * picker): the field shows "Nov 12, 2026" or "Select a date", and pressing it
 * drops the month down below it — previous and next, the caption that turns
 * to the year's months, the days from Sunday with today marked and days
 * outside the field's range closed, then Today and (for a field that may be
 * empty) Clear. The value stays an ISO day ("2026-11-12").
 *
 * The month opens in place under the field, in the form's own flow, so a
 * drawer or page scrolls to it however little room is left below.
 */
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react-native';

import { fonts, radius, useTheme } from '../theme';
import {
  MONTHS,
  WEEKDAYS,
  addMonths,
  compare,
  fromDate,
  isWithin,
  longLabel,
  monthCells,
  openingMonth,
  parseIso,
  shortLabel,
  toIso,
} from './calendar';
import type { Month } from './calendar';

const CALENDAR_PADDING = 12;
/** One day's square: seven fit the panel's width exactly. */
const CELL = 38;
const CALENDAR_WIDTH = CELL * 7 + CALENDAR_PADDING * 2;

interface DateFieldProps {
  readonly value: string;
  readonly onChange: (value: string) => void;
  readonly label: string;
  readonly min?: string;
  readonly max?: string;
  readonly isRequired?: boolean;
  readonly isReadOnly?: boolean;
  readonly hasError?: boolean;
  readonly placeholder?: string;
}

export function DateField({ value, onChange, label, min = '', max = '', isRequired, isReadOnly, hasError, placeholder }: DateFieldProps) {
  const { colors } = useTheme();
  const [isOpen, setIsOpen] = useState(false);
  const picked = parseIso(value);
  return (
    <>
      <Pressable
        onPress={() => setIsOpen(!isOpen)}
        disabled={isReadOnly}
        accessibilityRole="button"
        accessibilityLabel={`${label}: ${picked ? longLabel(picked) : 'no date'}`}
        accessibilityHint="Opens the calendar"
        accessibilityState={{ expanded: isOpen, disabled: isReadOnly }}
        style={[
          styles.field,
          {
            borderColor: hasError ? colors.danger : isOpen ? colors.primary : colors.fieldBorder,
            backgroundColor: isReadOnly ? colors.surfaceMuted : colors.surface,
          },
        ]}
      >
        <Text style={[styles.value, { color: picked ? colors.text : colors.textSubtle }]} numberOfLines={1}>
          {picked ? shortLabel(picked) : placeholder || 'Select a date'}
        </Text>
        <CalendarDays size={16} color={colors.textMuted} />
      </Pressable>
      {isOpen ? (
        <View
          accessibilityLabel={`${label} calendar`}
          style={[styles.panel, { backgroundColor: colors.raised, borderColor: colors.border }]}
        >
          <Calendar
            value={value}
            min={min}
            max={max}
            canClear={!isRequired}
            onPick={(next) => {
              onChange(next);
              setIsOpen(false);
            }}
          />
        </View>
      ) : null}
    </>
  );
}

interface CalendarProps {
  readonly value: string;
  readonly min: string;
  readonly max: string;
  readonly canClear: boolean;
  readonly onPick: (value: string) => void;
}

function Calendar({ value, min, max, canClear, onPick }: CalendarProps) {
  const { colors } = useTheme();
  const today = fromDate(new Date());
  const [month, setMonth] = useState<Month>(() => openingMonth(value, min, max, today));
  const [isMonths, setIsMonths] = useState(false);
  const picked = parseIso(value);
  const step = (by: number) => setMonth((now) => addMonths(now, isMonths ? by * 12 : by));
  return (
    <View style={styles.calendar}>
      <View style={styles.head}>
        <StepButton label={isMonths ? 'Previous year' : 'Previous month'} onPress={() => step(-1)} isNext={false} />
        <Pressable
          onPress={() => setIsMonths(!isMonths)}
          accessibilityRole="button"
          accessibilityLiveRegion="polite"
          accessibilityHint={isMonths ? 'Shows the days' : 'Shows the months'}
          style={styles.caption}
        >
          <Text style={[styles.captionText, { color: colors.text }]}>
            {isMonths ? month.y : `${MONTHS[month.m - 1]} ${month.y}`}
          </Text>
        </Pressable>
        <StepButton label={isMonths ? 'Next year' : 'Next month'} onPress={() => step(1)} isNext />
      </View>
      {isMonths ? (
        <View style={styles.months}>
          {MONTHS.map((name, index) => {
            const m = index + 1;
            const isOn = m === month.m;
            return (
              <Pressable
                key={name}
                onPress={() => {
                  setMonth({ y: month.y, m });
                  setIsMonths(false);
                }}
                accessibilityRole="button"
                accessibilityLabel={`${name} ${month.y}`}
                accessibilityState={{ selected: isOn }}
                style={[styles.month, isOn && { backgroundColor: colors.primarySoft }]}
              >
                <Text style={[styles.monthText, { color: isOn ? colors.link : colors.text }]}>{name.slice(0, 3)}</Text>
              </Pressable>
            );
          })}
        </View>
      ) : (
        <View accessibilityRole="grid">
          <View style={styles.week}>
            {WEEKDAYS.map((name) => (
              <Text key={name} style={[styles.dow, { color: colors.textMuted }]} accessibilityLabel={name}>
                {name.slice(0, 2)}
              </Text>
            ))}
          </View>
          <View style={styles.days}>
            {monthCells(month.y, month.m).map((day, index) => {
              if (!day) {
                return <View key={`blank-${index}`} style={styles.day} />;
              }
              const isOpen = isWithin(day, min, max);
              const isPicked = picked !== null && compare(day, picked) === 0;
              const isToday = compare(day, today) === 0;
              return (
                <Pressable
                  key={toIso(day)}
                  onPress={() => onPick(toIso(day))}
                  disabled={!isOpen}
                  accessibilityRole="button"
                  accessibilityLabel={longLabel(day)}
                  accessibilityState={{ selected: isPicked, disabled: !isOpen }}
                  style={[
                    styles.day,
                    isPicked && { backgroundColor: colors.primary },
                    !isPicked && isToday && { borderWidth: 1, borderColor: colors.primary },
                  ]}
                >
                  <Text
                    style={[
                      styles.dayText,
                      { color: isPicked ? colors.primaryInk : isOpen ? colors.text : colors.textSubtle },
                      !isOpen && styles.closed,
                    ]}
                  >
                    {day.d}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </View>
      )}
      <View style={[styles.foot, { borderTopColor: colors.raisedBorder }]}>
        <Pressable
          onPress={() => onPick(toIso(today))}
          disabled={!isWithin(today, min, max)}
          accessibilityRole="button"
          hitSlop={6}
        >
          <Text style={[styles.link, { color: isWithin(today, min, max) ? colors.link : colors.textSubtle }]}>Today</Text>
        </Pressable>
        {canClear ? (
          <Pressable onPress={() => onPick('')} accessibilityRole="button" hitSlop={6}>
            <Text style={[styles.link, { color: colors.link }]}>Clear</Text>
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

function StepButton({ label, onPress, isNext }: { readonly label: string; readonly onPress: () => void; readonly isNext: boolean }) {
  const { colors } = useTheme();
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={label} hitSlop={6} style={styles.step}>
      {isNext ? <ChevronRight size={18} color={colors.text} /> : <ChevronLeft size={18} color={colors.text} />}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  // The drawer's text input (drawerParts input): same height, corners and type.
  field: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8, minHeight: 40, borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 12 },
  value: { flex: 1, fontFamily: fonts.medium, fontSize: 16 },
  panel: { width: CALENDAR_WIDTH, alignSelf: 'flex-start', marginTop: 6, borderWidth: 1, borderRadius: radius.md, boxShadow: '0px 10px 24px -12px rgba(23, 48, 66, 0.35)' },
  calendar: { padding: CALENDAR_PADDING, gap: 8 },
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  step: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center', borderRadius: radius.sm },
  caption: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: radius.sm },
  captionText: { fontFamily: fonts.bold, fontSize: 14 },
  week: { flexDirection: 'row', width: CELL * 7 },
  dow: { width: CELL, height: 18, textAlign: 'center', fontFamily: fonts.semibold, fontSize: 11 },
  days: { flexDirection: 'row', flexWrap: 'wrap', width: CELL * 7 },
  day: { width: CELL, height: CELL, alignItems: 'center', justifyContent: 'center', borderRadius: CELL / 2 },
  dayText: { fontFamily: fonts.semibold, fontSize: 13 },
  closed: { textDecorationLine: 'line-through' },
  months: { flexDirection: 'row', flexWrap: 'wrap', rowGap: 6 },
  month: { width: '33.33%', height: 40, alignItems: 'center', justifyContent: 'center', borderRadius: radius.sm },
  monthText: { fontFamily: fonts.semibold, fontSize: 13 },
  foot: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', height: 44, borderTopWidth: 1, paddingTop: 4 },
  link: { fontFamily: fonts.semibold, fontSize: 13 },
});
