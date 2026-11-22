'use client';

/*
 * Record a country's next settings version (only before it is Active). The
 * form opens on the settings in force; the gateway checks it again, ends the
 * version before on the new one's start day, and rewrites nothing. After a
 * save the page's own tables are read again in place.
 */
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { EdifyDatePicker } from '@/components/ui/EdifyDatePicker';

import { postCountryAdmin } from '@/lib/countryAdminClient';
import { DATE_FORMATS, MAX_REASON, MONTH_CHOICES, TIME_ZONES, dateExample, languageList, settingsRequest } from '@/lib/countryAdmin';
import type { SettingsForm } from '@/lib/countryAdmin';

import { BUTTON_PRIMARY } from '../blocks/buttons';
import { Card } from '../blocks/Card';
import { FIELD, HINT, LABEL, NoticeLine } from './fields';

interface RecorderProps {
  readonly countryCode: string;
  readonly countryName: string;
  readonly initial: SettingsForm;
  readonly today: string;
  /** The start of the newest version recorded, or empty when there is none. */
  readonly latestFrom: string;
}

export function SettingsRecorder({ countryCode, countryName, initial, today, latestFrom }: RecorderProps) {
  const router = useRouter();
  const [form, setForm] = useState(initial);
  const [problem, setProblem] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof SettingsForm>(key: K, value: SettingsForm[K]) => setForm((f) => ({ ...f, [key]: value }));
  const languages = languageList(form.languages);

  const send = async (event: React.FormEvent) => {
    event.preventDefault();
    setNotice('');
    const request = settingsRequest(countryCode, form, today, latestFrom);
    if (typeof request === 'string') {
      setProblem(request);
      return;
    }
    setProblem('');
    setBusy(true);
    try {
      await postCountryAdmin('record', request);
      setForm({ ...form, from: '', reason: '' });
      setNotice(`${countryName}'s new settings are recorded${form.from ? ` from ${form.from}` : ' from today'}.`);
      router.refresh();
    } catch (error) {
      setProblem(error instanceof Error ? error.message : 'The settings could not be recorded.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card label="Record new settings">
      <h2 className="text-[length:var(--edify-text-title-size)] font-bold">Record New Settings</h2>
      <p className={HINT}>
        A new version starts on its date; the version before it ends that day and stays on record. {countryName} is not Active, so this changes how
        no one works today.
      </p>
      <form onSubmit={send} className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3" noValidate>
        <label className={LABEL}>
          Languages
          <input className={FIELD} name="languages" value={form.languages} onChange={(e) => set('languages', e.target.value)} placeholder="en, sw" />
          <span className={HINT}>Language codes, separated by commas.</span>
        </label>
        <label className={LABEL}>
          Default Language
          <select className={FIELD} name="defaultLanguage" value={form.defaultLanguage} onChange={(e) => set('defaultLanguage', e.target.value)}>
            {(languages.includes(form.defaultLanguage) ? languages : [form.defaultLanguage, ...languages]).map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </select>
        </label>
        <label className={LABEL}>
          Currency
          <input className={FIELD} name="currencyCode" value={form.currencyCode} maxLength={3} onChange={(e) => set('currencyCode', e.target.value.toUpperCase())} placeholder="KES" />
          <span className={HINT}>ISO 4217 code.</span>
        </label>
        <label className={LABEL}>
          Decimal Places
          <select className={FIELD} name="currencyMinorUnits" value={form.currencyMinorUnits} onChange={(e) => set('currencyMinorUnits', e.target.value)}>
            {['0', '1', '2', '3'].map((n) => (
              <option key={n} value={n}>
                {n === '0' ? '0 (whole amounts)' : n}
              </option>
            ))}
          </select>
        </label>
        <label className={LABEL}>
          Time Zone
          <input className={FIELD} name="timeZone" list="country-time-zones" value={form.timeZone} onChange={(e) => set('timeZone', e.target.value)} placeholder="Africa/Nairobi" />
          <datalist id="country-time-zones">
            {TIME_ZONES.map((zone) => (
              <option key={zone} value={zone} />
            ))}
          </datalist>
        </label>
        <label className={LABEL}>
          Date Format
          <select className={FIELD} name="dateFormat" value={form.dateFormat} onChange={(e) => set('dateFormat', e.target.value)}>
            {DATE_FORMATS.map((format) => (
              <option key={format} value={format}>
                {dateExample(format)} ({format})
              </option>
            ))}
          </select>
        </label>
        <label className={LABEL}>
          Financial Year Starts
          <select className={FIELD} name="fyStartMonth" value={form.fyStartMonth} onChange={(e) => set('fyStartMonth', e.target.value)}>
            {MONTH_CHOICES.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
        <fieldset className={LABEL}>
          <legend>Calendars</legend>
          <span className="mt-2 flex items-center gap-2 font-medium">
            <input type="checkbox" checked disabled aria-describedby="gregorian-kept" /> Gregorian
          </span>
          <span id="gregorian-kept" className={HINT}>
            Dates are always kept in Gregorian.
          </span>
          <label className="mt-1 flex items-center gap-2 font-medium">
            <input type="checkbox" name="ethiopian" checked={form.ethiopian} onChange={(e) => set('ethiopian', e.target.checked)} /> Ethiopian shown beside it
          </label>
        </fieldset>
        <div className={LABEL}>
          Starts
          <EdifyDatePicker name="effectiveFrom" label="Starts" min={today} value={form.from} onChange={(v) => set('from', v)} size="sm" policy={{ mode: 'free' }} />
          <span className={HINT}>Leave empty for today.</span>
        </div>
        <label className={`${LABEL} sm:col-span-2 lg:col-span-3`}>
          Reason
          <textarea className={FIELD} name="changeReason" rows={2} maxLength={MAX_REASON} value={form.reason} onChange={(e) => set('reason', e.target.value)} placeholder="What these settings are for" />
        </label>
        <div className="flex flex-wrap items-center gap-3 sm:col-span-2 lg:col-span-3">
          <button type="submit" className={`${BUTTON_PRIMARY} disabled:opacity-60`} disabled={busy}>
            {busy ? 'Recording…' : 'Record Settings'}
          </button>
          <NoticeLine problem={problem} notice={notice} />
        </div>
      </form>
    </Card>
  );
}
