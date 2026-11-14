"""Subprocess boundary gives document parsing a killable deadline."""
import json
import resource
import sys
resource.setrlimit(resource.RLIMIT_CPU,(110,110))
resource.setrlimit(resource.RLIMIT_FSIZE,(268435456,268435456))
if __name__=='__main__':
    from docling.document_converter import DocumentConverter
    result=DocumentConverter().convert(sys.argv[1],max_num_pages=500,max_file_size=33554432)
    document=result.document
    blocks=[]
    for item,_ in document.iterate_items():
        text=getattr(item,'text',None)
        if text:
            blocks.append({'text':text,'type':str(getattr(item,'label','text')),'provenance':[{'page':p.page_no,'bbox':p.bbox.model_dump()} for p in getattr(item,'prov',[])]})
    print(json.dumps({'markdown':document.export_to_markdown(),'blocks':blocks,'pages':len(document.pages),'complete':True,'warnings':[]},ensure_ascii=False))
