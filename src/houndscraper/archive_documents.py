"""Text-oriented EPUB and ODT extraction without external resource loading."""
import posixpath,zipfile
from xml.etree import ElementTree as ET
from bs4 import BeautifulSoup
from markdownify import markdownify

def xml(body):
    if b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper():raise ValueError('XML declarations with entities are unsupported')
    return ET.fromstring(body)

def convert(path):
    with zipfile.ZipFile(path) as archive:
        entries=archive.infolist()
        if len(entries)>10000 or sum(i.file_size for i in entries)>268435456 or any(i.file_size>67108864 or i.flag_bits&1 for i in entries):raise ValueError('Unsafe document archive')
        blocks=[];sections=[];supported=True
        if path.suffix.lower()=='.epub':
            import urllib.parse
            container=xml(archive.read('META-INF/container.xml'))
            package=next(e.attrib['full-path'] for e in container.iter() if e.tag.endswith('}rootfile'))
            root=xml(archive.read(package));base=posixpath.dirname(package)
            manifest={e.attrib['id']:e.attrib for e in root.iter() if e.tag.endswith('}item')}
            for ref in (e for e in root.iter() if e.tag.endswith('}itemref')):
                item=manifest[ref.attrib['idref']]
                if item.get('media-type') not in ('application/xhtml+xml','text/html'):supported=False;continue
                href=urllib.parse.urlsplit(item['href'])
                if href.scheme or href.netloc:raise ValueError('External EPUB chapters are unsupported')
                name=posixpath.normpath(posixpath.join(base,urllib.parse.unquote(href.path)))
                if name.startswith('../') or name.startswith('/'):raise ValueError('Invalid EPUB chapter path')
                soup=BeautifulSoup(archive.read(name),'html.parser')
                for tag in soup(['script','style','iframe','object']):tag.decompose()
                text=soup.get_text(' ',strip=True);sections.append(markdownify(str(soup)).strip());blocks.append({'text':text,'type':'chapter','provenance':[{'archive_path':name}]})
        else:
            root=xml(archive.read('content.xml'))
            for e in root.iter():
                if e.tag.rsplit('}',1)[-1] in ('p','h'):
                    text=''.join(e.itertext()).strip()
                    if text:sections.append(text);blocks.append({'text':text,'type':'paragraph','provenance':[{'archive_path':'content.xml'}]})
        return {'markdown':'\n\n'.join(sections),'blocks':blocks,'pages':0,'total_pages':None,'complete':bool(sections) and supported,'warnings':['Text-oriented extraction; page layout and embedded media are not reconstructed']}
