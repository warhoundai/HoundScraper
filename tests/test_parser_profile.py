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
    path=tmp_path/'speech.wav'
    subprocess.run(['espeak-ng','-w',str(path),'The invoice total is forty two dollars.'],check=True)
    result=convert(path,language='en');text=result['markdown'].lower()
    assert 'invoice' in text and ('dollar' in text or '42' in text)
