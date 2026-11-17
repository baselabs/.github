"""Give actionlint each composite's literal inline scripts as workflow steps.

actionlint accepts workflows, not action metadata. Keep scripts unchanged in a
temporary workflow so actionlint's shell analysis also covers composite actions.
"""
import json
from pathlib import Path
import re
import subprocess
import textwrap

for action in sorted(Path('actions').glob('*/action.yml')):
    lines = action.read_text().splitlines(keepends=True)
    steps = []
    for i, line in enumerate(lines):
        match = re.fullmatch(r'( +)run: \|\n', line)
        if not match:
            continue
        indentation = len(match[1])
        body = []
        for following in lines[i + 1:]:
            if following.strip() and len(following) - len(following.lstrip()) <= indentation:
                break
            body.append(following)
        steps.append({'shell': 'bash', 'run': textwrap.dedent(''.join(body))})
    if not steps:
        raise SystemExit(str(action) + ': no literal inline scripts found')
    workflow = {'name': 'composite scripts', 'on': 'push', 'jobs': {
        'scripts': {'runs-on': 'ubuntu-24.04', 'steps': steps}}}
    subprocess.run(['actionlint', '-stdin-filename', str(action), '-'],
                   input=json.dumps(workflow), text=True, check=True)
