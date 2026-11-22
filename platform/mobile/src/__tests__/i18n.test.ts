import { tMobile } from '../i18n';

describe('mobile multi-country i18n', () => {
  it('resolves Cluster Leader and fieldwork strings in all 6 languages', () => {
    expect(tMobile('en', 'planMeeting')).toBe('Plan Meeting');
    expect(tMobile('sw', 'planMeeting')).toBe('Panga Mkutano');
    expect(tMobile('rw', 'planMeeting')).toBe('Tegura Inama');
    expect(tMobile('fr', 'planMeeting')).toBe('Planifier une réunion');
    expect(tMobile('am', 'planMeeting')).toBe('ስብሰባ አቅድ');
    expect(tMobile('om', 'planMeeting')).toBe('Walgahii Karoorsi');
    expect(tMobile('unknown', 'home')).toBe('Home');
  });
});
