'use client';

/*
 * A form a page shows itself (the Daily Debrief's questions), drawn and saved
 * here when the gateway marks that it saves it: its fields are the drawer's
 * own, its save is the page's path with the form's key, and the page is read
 * again once it is saved.
 */
import { toJson } from '@bufbuild/protobuf';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import type { FormEvent } from 'react';

import { submitPageForm } from '@/app/(app)/actions/drawer';
import { DrawerFormItem } from '@/components/drawer/DrawerHost';
import { PageFormSchema } from '@/gen/edify/screens/v1/page_pb';
import type { PageForm } from '@/gen/edify/screens/v1/page_pb';
import { initialValues, valuesToSend } from '@/lib/drawerLogic';
import type { DrawerFieldJson, DrawerJson } from '@/lib/drawerLogic';

import { BUTTON_PRIMARY } from '../blocks/buttons';

interface PageFormInlineProps {
  readonly form: PageForm;
  readonly pagePath: string;
}

interface Said {
  readonly busy: boolean;
  readonly error: string;
  readonly message: string;
}

export function PageFormInline({ form, pagePath }: PageFormInlineProps) {
  const router = useRouter();
  const drawer = toJson(PageFormSchema, form) as DrawerJson;
  const [values, setValues] = useState<Record<string, string>>(() => initialValues(drawer));
  const [said, setSaid] = useState<Said>({ busy: false, error: '', message: '' });
  const change = (field: DrawerFieldJson, value: string) => setValues((current) => ({ ...current, [field.name ?? '']: value }));

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaid({ busy: true, error: '', message: '' });
    const answer = await submitPageForm(pagePath, form.key, valuesToSend(drawer, values));
    if (!answer.saved) {
      setSaid({ busy: false, error: answer.error || 'This could not be saved. Nothing was changed.', message: '' });
      return;
    }
    setSaid({ busy: false, error: '', message: answer.message || 'Saved.' });
    if (answer.redirect) router.push(answer.redirect);
    else router.refresh();
  };

  return (
    <section aria-label={form.title || form.submitLabel} data-block="form" className="card p-4 shadow-[var(--edify-shadow-sm)]">
      {form.title ? <h2 className="text-[length:var(--edify-text-title-size)] font-bold">{form.title}</h2> : null}
      {form.text ? <p className="mt-1 text-[var(--edify-text-muted)]">{form.text}</p> : null}
      <form onSubmit={(event) => void save(event)} className="mt-3 space-y-3">
        {(drawer.items ?? []).map((item, index) => (
          <DrawerFormItem key={index} item={item} values={values} reloaded={{}} onChange={change} />
        ))}
        {said.error ? <p role="alert" className="text-[length:var(--edify-text-label-size)] font-semibold text-[var(--edify-danger-text,inherit)]">{said.error}</p> : null}
        {said.message ? <p role="status" className="text-[length:var(--edify-text-label-size)] font-semibold text-[var(--edify-success-text,inherit)]">{said.message}</p> : null}
        <button type="submit" disabled={said.busy} className={`${BUTTON_PRIMARY} h-10 px-4`}>
          {said.busy ? 'Saving…' : form.submitLabel || 'Save'}
        </button>
      </form>
    </section>
  );
}
