"""Document the design-system inheritance of every page template."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / 'templates'

def ancestry(path):
    chain = []
    while path.exists() and str(path.relative_to(TEMPLATES)) not in chain:
        chain.append(str(path.relative_to(TEMPLATES)))
        match = re.search(r'{%\s*extends\s+[\"\']([^\"\']+)', path.read_text())
        if not match:
            if '{% extends base_template %}' in path.read_text():
                # Verified full-page branches in planning/core-schools and BT views.
                path = TEMPLATES / 'layouts/shell.html'
                continue
            break
        path = TEMPLATES / match.group(1)
    return chain

records = []
for path in sorted((TEMPLATES / 'pages').rglob('*.html')):
    chain = ancestry(path)
    source = path.read_text()
    if 'layouts/shell.html' in chain:
        family = 'workspace'
    elif any(layout in chain for layout in ['base.html', 'layouts/login.html']):
        family = 'public or authentication'
    elif 'css/design-system.css' in source:
        family = 'print document'
    else:
        family = 'embedded fragment'
    records.append({'template': chain[0], 'family': family, 'inheritance': chain,
                    'shared_design_system': family != 'embedded fragment',
                    'header': 'shared' if any(term in source for term in ['edify-page-header','edify-page-hero','platform-hero','platform-page-header']) else 'family-owned or inherited'})
result = {'design': 'Calm workspace', 'pages': records,
          'summary': {family: sum(r['family'] == family for r in records) for family in sorted({r['family'] for r in records})}}
(ROOT / 'docs/ui-surface-inventory.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result['summary']))
