"""Archive public challenge documentation using only the Python standard library."""

from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


class Document(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.text = []
        self.links = set()

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'svg'):
            self.hidden += 1
        if tag == 'a':
            self.links.update(value for key, value in attrs if key == 'href' and value)
        if tag in ('p', 'div', 'section', 'h1', 'h2', 'h3', 'li', 'pre', 'tr', 'br'):
            self.text.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'svg'):
            self.hidden = max(0, self.hidden - 1)
        if tag in ('p', 'div', 'section', 'li', 'pre', 'tr'):
            self.text.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)


def main():
    now = datetime.now(timezone.utc)
    root = Path(__file__).resolve().parents[1] / 'docs' / 'upstream'
    folder = root / now.strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True, exist_ok=True)
    sources = {
        'home': 'https://htn.dryft.ai/',
        'participant-guide': 'https://htn.dryft.ai/docs',
        'starter': 'https://github.com/Dryft-Kernels/starter',
        'engine-contract': 'https://github.com/Dryft-Kernels/starter/blob/main/QWEN_ENGINE_CONTRACT.md',
    }
    manifest = {'fetched_at_utc': now.isoformat(), 'sources': []}
    for name, url in sources.items():
        record = {'name': name, 'url': url}
        try:
            request = Request(url, headers={'User-Agent': 'Dryft-Participant-Docs/1.0'})
            with urlopen(request, timeout=30) as response:
                raw = response.read()
                record.update(status=response.status, final_url=response.url,
                              sha256=sha256(raw).hexdigest())
            (folder / f'{name}.html').write_bytes(raw)
            doc = Document()
            doc.feed(raw.decode('utf-8', errors='replace'))
            lines = [line.strip() for line in ''.join(doc.text).splitlines() if line.strip()]
            (folder / f'{name}.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
            record['links'] = sorted({urljoin(url, link) for link in doc.links})
        except (HTTPError, URLError, TimeoutError) as error:
            record.update(status=getattr(error, 'code', None), error=str(error))
        manifest['sources'].append(record)
        print(f"{name}: {record.get('status')} {record.get('error', 'saved')}")
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    (root / 'latest.json').write_text(json.dumps({'snapshot': folder.name}, indent=2) + '\n', encoding='utf-8')
    print(f'Snapshot: {folder}')
    if any('error' in source for source in manifest['sources'][:2]):
        raise SystemExit('Could not archive all primary challenge pages; see manifest.')


if __name__ == '__main__':
    main()
