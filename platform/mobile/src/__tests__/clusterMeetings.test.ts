import { channelLabel, isTimeText, planStatus, ssaStatusLabel, newSubmissionKey } from '../screens/cluster/clusterData';
import { safeFileName } from '../ui/savePdf';

describe("a meeting plan's status reads in words", () => {
  test('a submitted plan is Planned, with what that means', () => {
    expect(planStatus('submitted')).toEqual({ label: 'Planned', tone: 'info', meaning: 'Sent to your CCEO for review.' });
    expect(planStatus('returned').label).toBe('Returned');
    expect(planStatus('scheduled').meaning).toContain('Invitations carried over');
  });

  test('an unknown status is shown as it is, never hidden', () => {
    expect(planStatus('archived').label).toBe('archived');
  });
});

describe('the time field', () => {
  test.each(['10:00 AM', '9:30', '14.15', '7:05pm', ''])('accepts %p', (value) => {
    expect(isTimeText(value)).toBe(true);
  });
  test.each(['ten', '25:00', '10:60 AM'])('refuses %p', (value) => {
    expect(isTimeText(value)).toBe(false);
  });
});

test('channels read as people say them', () => {
  expect(channelLabel('in_person')).toBe('In person');
  expect(channelLabel('sms')).toBe('SMS');
});

test('a report file name is safe on every phone', () => {
  expect(safeFileName('Cluster report - Kampala/East - FY 2027.pdf')).toBe('Cluster report - Kampala-East - FY 2027.pdf');
  expect(safeFileName('Report: "Q1"')).toBe('Report- -Q1-.pdf');
  expect(safeFileName('')).toBe('report.pdf');
});

test("SSA statuses read as the web's own words", () => {
  expect(ssaStatusLabel('not_done')).toBe('Not Done');
  expect(ssaStatusLabel('partner_assigned')).toBe('Partner Assigned');
});

describe('a Cluster Action submission key', () => {
  test('each form gets its own, short enough for the gateway', () => {
    const keys = new Set(Array.from({ length: 500 }, () => newSubmissionKey(1_800_000_000_000)));
    expect(keys.size).toBe(500);
    for (const key of keys) {
      expect(key.length).toBeLessThanOrEqual(100);
      expect(key).toMatch(/^ca-[0-9a-z]+-[0-9a-z]{16}$/);
    }
  });
});
