import {
  appointmentActions,
  cancelConsequence,
  isWorkingAsActing,
  offersWorkAs,
  stateTone,
  workAsChoices,
} from '../screens/acting/actingData';

const acting = {
  appointmentId: 'a1',
  label: 'Acting Program Lead',
  shortLabel: 'Acting PL',
  monthLabel: 'November 2026',
  seatName: 'John Lead',
  appointeeRole: 'CCEO',
  inCapacity: true,
} as never;

describe('Work as, with an acting appointment (the web role switcher)', () => {
  test('the acting capacity sits beside the roles held, and is current while in use', () => {
    expect(workAsChoices({ roles: ['CCEO'], activeRole: 'CCEO', acting })).toEqual([
      { key: 'CCEO', label: 'CCEO', isCurrent: false },
      { key: 'acting', label: 'Acting Program Lead · November 2026', isCurrent: true },
    ]);
  });

  test('switched off, or working in another role, the role is current', () => {
    const off = { ...(acting as object), inCapacity: false } as never;
    expect(workAsChoices({ roles: ['CCEO'], activeRole: 'CCEO', acting: off }).map((c) => c.isCurrent)).toEqual([true, false]);
    expect(isWorkingAsActing({ activeRole: 'ProjectCoordinator', acting })).toBe(false);
  });

  test('is offered for one role when there is an appointment, and not otherwise', () => {
    expect(offersWorkAs({ roles: ['CCEO'], acting })).toBe(true);
    expect(offersWorkAs({ roles: ['CCEO'], acting: undefined })).toBe(false);
    expect(offersWorkAs({ roles: ['CCEO', 'ProjectCoordinator'], acting: undefined })).toBe(true);
  });
});

describe('an appointment row', () => {
  test('offers only what the gateway allows', () => {
    expect(appointmentActions({ canChangeMonth: true, canCancel: true })).toEqual(['change', 'cancel']);
    expect(appointmentActions({ canChangeMonth: false, canCancel: true })).toEqual(['cancel']);
    expect(appointmentActions({ canChangeMonth: false, canCancel: false })).toEqual([]);
  });

  test('colours its state', () => {
    expect(['active', 'upcoming', 'expired', 'cancelled'].map(stateTone)).toEqual(['good', 'info', 'plain', 'alert']);
  });

  test('says what cancelling does, in the web words', () => {
    const row = { appointeeName: 'Sarah N.', shortLabel: 'Acting PL', appointeeRole: 'CCEO', monthLabel: 'December 2026' };
    expect(cancelConsequence({ ...row, state: 'active' })).toBe(
      'Sarah N. loses Acting PL access at once and returns to working as CCEO.',
    );
    expect(cancelConsequence({ ...row, state: 'upcoming' })).toBe(
      'Sarah N. will not become Acting PL in December 2026. The appointment stays in History.',
    );
  });
});
