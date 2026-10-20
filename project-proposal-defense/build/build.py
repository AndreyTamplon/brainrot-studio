from pathlib import Path
import base64
import json
import mimetypes
import re

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / 'assets'
BUILD = ROOT / 'build'

def data_uri(name):
    path = ASSETS / name
    mime = mimetypes.guess_type(name)[0] or 'application/octet-stream'
    if name.endswith('.ttf'):
        mime = 'font/ttf'
    return 'data:' + mime + ';base64,' + base64.b64encode(path.read_bytes()).decode()

fonts = (ASSETS / 'fonts.css').read_text()
fonts = re.sub(r'url\((manrope-[^)]+)\)', lambda m: 'url(' + data_uri(m.group(1)) + ')', fonts)
html = (BUILD / 'deck.source.html').read_text()
html = html.replace('@@FONTS@@', fonts).replace('@@CSS@@', (BUILD / 'deck.css').read_text() + '\n' + (BUILD / 'revision.css').read_text())
html = html.replace('@@JS@@', (BUILD / 'deck.js').read_text())
html = re.sub(r'@@ASSET:([^@]+)@@', lambda m: data_uri(m.group(1)), html)
html = html.replace('@@FONT_LICENSE@@', (ASSETS / 'font-license.txt').read_text().replace('--', '-'))
if '@@' in html:
    raise ValueError('An unresolved build token remains')
html = html.translate(str.maketrans({'ё': 'е', 'Ё': 'Е', **{c: '-' for c in '\u2010\u2011\u2012\u2013\u2014\u2015\u2212'}}))
target = ROOT / 'brainrot-studio-proposal.html'
target.write_text(html)
print(json.dumps({'file': str(target), 'bytes': target.stat().st_size}, ensure_ascii=False))
