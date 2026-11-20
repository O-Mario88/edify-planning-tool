import { splitHeroes } from '../screens/homeHeroes';

const figures = ['upcoming', 'under_way', 'overdue', 'waiting_me'].map((key) => ({ key }));

describe('Home’s hero figures', () => {
  test('a CCEO’s are Overdue and Waiting on you, first, the rest after (owner, 2026-11-20)', () => {
    const { heroes, rest } = splitHeroes(figures, 'CCEO');
    expect(heroes.map((f) => f.key)).toEqual(['overdue', 'waiting_me']);
    expect(rest.map((f) => f.key)).toEqual(['upcoming', 'under_way']);
  });

  test('every role with its own plan leads with Overdue and To-Do (the partners)', () => {
    const { heroes } = splitHeroes(figures, 'Partner');
    expect(heroes.map((f) => f.key)).toEqual(['overdue', 'waiting_me']);
  });

  test('a desk role leads with Critical and To-Do (the Country Director, IA, the Accountant)', () => {
    const desk = ['waiting_me', 'due_today', 'critical'].map((key) => ({ key }));
    const { heroes, rest } = splitHeroes(desk, 'Country Director');
    expect(heroes.map((f) => f.key)).toEqual(['critical', 'waiting_me']);
    expect(rest.map((f) => f.key)).toEqual(['due_today']);
  });

  test('figures with neither keep their order, none a hero', () => {
    const { heroes, rest } = splitHeroes([{ key: 'due_today' }, { key: 'upcoming' }], 'Admin');
    expect(heroes).toEqual([]);
    expect(rest.map((f) => f.key)).toEqual(['due_today', 'upcoming']);
  });
});
