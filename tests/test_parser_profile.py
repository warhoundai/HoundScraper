"""Optional real-model qualification, enabled only in the parser profile job."""
import os,subprocess,json,sys
from pathlib import Path
import pytest
pytestmark=pytest.mark.skipif(os.environ.get('HOUNDSCRAPER_TEST_PARSER')!='1',reason='Requires separately provisioned offline parser models')
def convert(path,language=None):
    r=subprocess.run([sys.executable,'-m','houndscraper.parser_process',str(path)],capture_output=True,text=True,timeout=120,env={**os.environ,**({'HOUNDSCRAPER_MEDIA_LANGUAGE':language} if language else {})})
    assert r.returncode==0,r.stderr[-2000:]
    return json.loads(r.stdout)
def test_real_office_document(tmp_path):
    from docx import Document
    d=Document();d.add_heading('Verified document fixture',0);d.add_paragraph('Invoice total 42 dollars');path=tmp_path/'fixture.docx';d.save(path)
    result=convert(path);assert '42' in result['markdown'] and 'Verified' in result['markdown']
def test_real_pdf_text_layout_and_table(tmp_path):
    from reportlab.pdfgen import canvas
    path=tmp_path/'fixture.pdf';c=canvas.Canvas(str(path));c.drawString(72,750,'Invoice total 42 dollars');c.drawString(72,720,'Evidence from a controlled PDF fixture.');c.save()
    result=convert(path);assert '42' in result['markdown'] and result['blocks'] and result['pages']==1
    assert any(p['page']==1 for b in result['blocks'] for p in b['provenance'])
def test_real_scanned_pdf_ocr(tmp_path):
    from PIL import Image,ImageDraw,ImageFont
    image=Image.new('RGB',(1200,1000),'white');draw=ImageDraw.Draw(image);font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',48);draw.text((100,150),'Invoice total 42 dollars',font=font,fill='black')
    path=tmp_path/'scan.pdf';image.save(path,'PDF');result=convert(path);assert '42' in result['markdown']

def test_real_audio_transcription(tmp_path):
    # Public-domain JFK inaugural excerpt, as used by upstream Whisper's MIT test suite.
    # Download only during explicit qualification, not in offline parser runtime.
    import urllib.request,hashlib,re
    url='https://raw.githubusercontent.com/openai/whisper/86098128c0b4f24f0e2aa2994de830614b474227/tests/jfk.flac'
    with urllib.request.urlopen(url,timeout=30) as response:body=response.read(2000000)
    assert hashlib.sha256(body).hexdigest()=='63a4b1e4c1dc655ac70961ffbf518acd249df237e5a0152faae9a4a836949715'
    path=tmp_path/'speech.flac';path.write_bytes(body)
    result=convert(path,language='en');actual=re.findall(r"[a-z]+",result['markdown'].lower())
    expected='and so my fellow americans ask not what your country can do for you ask what you can do for your country'.split()
    row=list(range(len(actual)+1))
    for i,word in enumerate(expected,1):
        next_row=[i]
        for j,seen in enumerate(actual,1):next_row.append(min(next_row[-1]+1,row[j]+1,row[j-1]+(word!=seen)))
        row=next_row
    wer=row[-1]/len(expected)
    assert wer<=.2,{'word_error_rate':wer,'transcript':result['markdown']}

def test_real_spreadsheet_and_presentation(tmp_path):
    from openpyxl import Workbook
    from pptx import Presentation
    workbook=Workbook();workbook.active.append(['Item','Amount']);workbook.active.append(['Invoice',42]);sheet=tmp_path/'fixture.xlsx';workbook.save(sheet)
    assert '42' in convert(sheet)['markdown']
    slides=Presentation();slide=slides.slides.add_slide(slides.slide_layouts[1]);slide.shapes.title.text='Invoice evidence';slide.placeholders[1].text='Invoice total 42 dollars';presentation=tmp_path/'fixture.pptx';slides.save(presentation)
    assert '42' in convert(presentation)['markdown']

def test_real_csv_table(tmp_path):
    path=tmp_path/'fixture.csv';path.write_text('item,amount\ninvoice,42\n')
    result=convert(path);assert '42' in result['markdown'] and 'invoice' in result['markdown'].lower()
