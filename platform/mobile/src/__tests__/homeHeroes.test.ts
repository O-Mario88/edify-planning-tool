import { splitHeroes } from '../screens/homeHeroes';

const figures = ['upcoming', 'under_way', 'overdue', 'waiting_me'].map((key) => ({ key }));

describe('Home’s hero figures', () => {
  test('a CCEO’s are Overdue and Waiting on you, first, the rest after (owner, 2026-11-20)', () => {
    const { heroes, rest } = splitHeroes(figures, 'CCEO');
    expect(heroes.map((f) => f.key)).toEqual(['overdue', 'waiting_me']);
    expect(rest.map((f) => f.key)).toEqual(['upcoming', 'under_way']);
  });

  test('another role has none and keeps its figures as they come', () => {
    const { heroes, rest } = splitHeroes(figures, 'Accountant');
    expect(heroes).toEqual([]);
    expect(rest.map((f) => f.key)).toEqual(['upcoming', 'under_way', 'overdue', 'waiting_me']);
  });
});
