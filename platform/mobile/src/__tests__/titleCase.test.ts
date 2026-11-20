import { titleCase } from '../ui/page/titleCase';

describe('a column name in Title Case', () => {
  test('capitalises each word but keeps the small words lower case inside the name', () => {
    expect(titleCase('Part of the plan')).toBe('Part of the Plan');
    expect(titleCase('School / Cluster')).toBe('School / Cluster');
    expect(titleCase('visits planned for the year')).toBe('Visits Planned for the Year');
    expect(titleCase('of')).toBe('Of');
    expect(titleCase('Worth looking at')).toBe('Worth Looking At');
  });

  test('keeps initialisms, codes and figures as written', () => {
    expect(titleCase('School ID')).toBe('School ID');
    expect(titleCase('Visits FY2027')).toBe('Visits FY2027');
    expect(titleCase('SSA score')).toBe('SSA Score');
    expect(titleCase('Total (UGX)')).toBe('Total (UGX)');
    expect(titleCase('')).toBe('');
  });
});
