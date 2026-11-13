import { describe, expect, it } from 'vitest';

import { isPagePart, pagePartUrl } from './pagePart';

describe('isPagePart', () => {
  it('takes a cluster card’s schools', () => {
    expect(isPagePart('/partials/clusters/cmw9p8e4900p50wekhe46/schools')).toBe(true);
  });

  it('refuses any other path, a drawer included', () => {
    for (const path of ['/clusters', '/partials/clusters/x/schools/../../admin', '/clusters/x/bulk-assign-drawer', '/partials/clusters//schools', 'https://x/partials/clusters/a/schools']) {
      expect(isPagePart(path)).toBe(false);
    }
  });

  it('asks this app’s own route with the path as its query', () => {
    expect(pagePartUrl('/partials/clusters/abc/schools')).toBe('/page-parts?path=%2Fpartials%2Fclusters%2Fabc%2Fschools');
  });
});
