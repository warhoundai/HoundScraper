"""Subprocess boundary gives document parsing a killable deadline."""
import json
import resource
import sys
resource.setrlimit(resource.RLIMIT_CPU,(110,110))
resource.setrlimit(resource.RLIMIT_FSIZE,(268435456,268435456))
if __name__=='__main__':
    import os
    from pathlib import Path
    import contextlib
    if Path(sys.argv[1]).suffix.lower() in ('.epub','.odt'):
        from .archive_documents import convert
        print(json.dumps(convert(Path(sys.argv[1])),ensure_ascii=False));sys.exit(0)
    with contextlib.redirect_stdout(sys.stderr):
        from docling.document_converter import DocumentConverter,PdfFormatOption,AudioFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions,AsrPipelineOptions
        artifacts=os.environ.get('DOCLING_ARTIFACTS_PATH','/models')
        formats={InputFormat.PDF:PdfFormatOption(pipeline_options=PdfPipelineOptions(artifacts_path=artifacts,enable_remote_services=False))}
        if Path(sys.argv[1]).suffix.lower() in ('.wav','.mp3','.flac','.m4a','.ogg'):
            from docling.datamodel import asr_model_specs
            from docling.pipeline.asr_pipeline import AsrPipeline
            options=AsrPipelineOptions(artifacts_path=artifacts,enable_remote_services=False)
            options.asr_options=asr_model_specs.WHISPER_TINY_NATIVE.model_copy(update={'language':os.environ.get('HOUNDSCRAPER_MEDIA_LANGUAGE')})
            formats[InputFormat.AUDIO]=AudioFormatOption(pipeline_cls=AsrPipeline,pipeline_options=options)
        result=DocumentConverter(format_options=formats).convert(sys.argv[1],max_num_pages=500,max_file_size=33554432)
        document=result.document
        blocks=[]
        for item,_ in document.iterate_items():
            text=getattr(item,'text',None)
            if text:
                blocks.append({'text':text,'type':str(getattr(item,'label','text')),'provenance':[{'page':p.page_no,'bbox':p.bbox.model_dump()} for p in getattr(item,'prov',[])]})
    print(json.dumps({'markdown':document.export_to_markdown(),'blocks':blocks,'pages':len(document.pages),'total_pages':getattr(result.input,'page_count',None),'complete':getattr(result.status,'value',str(result.status)).lower()=='success','warnings':[] if getattr(result.status,'value',str(result.status)).lower()=='success' else ['Document conversion reported incomplete output']},ensure_ascii=False))
