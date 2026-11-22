import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { SsaUploadCenterView } from './SsaUploadCenterView';

describe('SsaUploadCenterView', () => {
  it('renders the Bulk Upload Center with SSA template download, file input, and required columns', () => {
    const html = renderToStaticMarkup(<SsaUploadCenterView />);
    expect(html).toContain('Bulk Upload Center');
    expect(html).toContain('Official SSA Scores CSV');
    expect(html).toContain('Planned Activities Completion CSV');
    expect(html).toContain('/ssa/upload/template');
    expect(html).toContain('type="file"');
    expect(html).toContain('School ID');
    expect(html).toContain('Assessment Date');
    expect(html).toContain('Upload and Import');
  });
});
