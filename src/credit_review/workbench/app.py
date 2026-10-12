"""Same-origin local workbench API, deliberately bound to loopback by launcher."""
from __future__ import annotations
import hashlib
import io
import json
import os
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from credit_review.domain.errors import ConflictError
from credit_review.rules.engine import default_rules
from .storage import Store, encode
from .knowledge import Knowledge, MAX_BYTES
from .reviews import Reviews
from .gateway import PROJECT, Gateway, load_settings
from .provider.config import read_env, Settings
from .exports import html_report, pdf_report, csv_report, bundle, esc


def create_workbench_app(root=None, backend=None, gateway_factory=None):
    store = Store(root or os.getenv('CREDIT_REVIEW_DATA_DIR') or PROJECT / '.local-data')
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='credit-review')
    values = {**read_env(PROJECT / '.env'), **os.environ}
    knowledge = Knowledge(store, executor, backend=backend or values.get('CREDIT_REVIEW_RETRIEVAL_BACKEND', 'sentence_transformers'),
                          embedding_model=values.get('CREDIT_REVIEW_EMBEDDING_MODEL', 'moka-ai/m3e-base'),
                          reranker_model=values.get('CREDIT_REVIEW_RERANKER_MODEL', 'BAAI/bge-reranker-v2-m3'))
    reviews = Reviews(store, knowledge, executor, gateway_factory=gateway_factory)
    for build in store.list('build'):
        if build['status'] not in {'READY', 'FAILED', 'CANCELLED', 'INTERRUPTED'}:
            build.update(status='INTERRUPTED', error='建库被服务重启中断，请创建新版本。')
            store.save('build', build['build_id'], build)
            store.append(build['build_id'], 'process_interrupted', {})
    @asynccontextmanager
    async def lifespan(app):
        yield
        executor.shutdown(wait=False, cancel_futures=True)
    app = FastAPI(title='金融信贷分析报告智能复核工作台', version='0.2.0', lifespan=lifespan)
    app.state.store, app.state.knowledge, app.state.reviews = store, knowledge, reviews

    @app.middleware('http')
    async def local_origin(request: Request, call_next):
        # Block browser cross-site access to local documents and model settings.
        host = request.headers.get('host', '').split(':')[0]
        if host not in {'127.0.0.1', 'localhost', 'testserver', '[', '::1'}:
            return JSONResponse({'detail': '本地工作台仅接受 loopback Host。'}, status_code=403)
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail': '不允许跨站访问本地工作台。'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({'detail': '任务、文件或知识库不存在。'}, status_code=404)
    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=400)
    @app.exception_handler(ConflictError)
    async def conflict(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=409)

    def runtime_info():
        config = load_settings()
        try:
            config.validate()
            error = None
        except ValueError as exc: error = str(exc)
        return {'status': 'ok', 'application_version': '0.2.0', 'mode': '真实模型复核', 'provider': config.public(),
                'provider_validation_error': error, 'retrieval_backend': knowledge.backend,
                'embedding_model': knowledge.embedding_model if knowledge.backend == 'sentence_transformers' else None,
                'reranker_model': knowledge.reranker_model if knowledge.backend == 'sentence_transformers' else None,
                'persistence': 'SQLite + 原件 + 版本化知识库', 'data_dir': str(store.root), 'rule_set_version': 'credit-review-workbench-v1'}
    @app.get('/health/live')
    def health(): return runtime_info()
    @app.get('/v1/runtime')
    def runtime(): return runtime_info()
    @app.post('/v1/provider/check')
    def provider_check():
        ident = 'CONNECTION-' + hashlib.sha256(os.urandom(32)).hexdigest()[:12]
        gateway = Gateway(store, ident)
        store.append(ident, 'connection_check', {'configuration': gateway.config.public()})
        try:
            reply = gateway.healthcheck()
            store.append(ident, 'connection_result', {'ok': True, 'reply': reply})
            return {'ok': True, 'reply': reply, 'audit_job': ident}
        except Exception as exc:
            store.append(ident, 'connection_result', {'ok': False, 'error': str(exc)})
            return {'ok': False, 'error': str(exc), 'audit_job': ident}
    @app.put('/v1/provider')
    def update_provider(payload: dict[str, Any]):
        with reviews.lock:
            if any(r['status'] in {'RUNNING', 'QUEUED'} for r in store.list('review')):
                raise ConflictError('运行中的复核须完成或取消后再更换 API 配置。')
            old = load_settings()
            new = Settings(api_key=payload.get('api_key') or old.api_key, base_url=payload.get('base_url', old.base_url), model=payload.get('model', old.model),
                           wire_api=payload.get('wire_api', old.wire_api), headers=payload.get('headers', old.headers),
                           stream=bool(payload.get('stream', old.stream)), timeout=old.timeout, retries=old.retries, max_tokens=old.max_tokens, structured=False)
            new.validate()
            env = read_env(PROJECT / '.env')
            env.update({'LLM_BASE_URL': new.base_url, 'LLM_MODEL': new.model, 'LLM_WIRE_API': new.wire_api,
                        'LLM_API_KEY': new.api_key, 'LLM_HTTP_HEADERS': json.dumps(new.headers), 'LLM_STREAM': str(new.stream).lower(), 'LLM_STRUCTURED_OUTPUT': 'false'})
            target = PROJECT / '.env'
            temporary = PROJECT / '.env.workbench-tmp'
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, 'w') as handle:
                handle.write('\n'.join(k + '=' + v for k, v in env.items()) + '\n')
            temporary.replace(target)
            target.chmod(0o600)
            store.append('CONFIGURATION', 'provider_updated', {'before': old.public(), 'after': new.public(), 'credential_changed': bool(payload.get('api_key'))}, 'local-reviewer')
            return new.public()

    @app.get('/v1/documents')
    def documents(): return store.list('document')
    @app.post('/v1/documents')
    async def upload(file: UploadFile = File(...), company: str = Form(''), period: str = Form(''), original_document_id: str = Form('')):
        from starlette.concurrency import run_in_threadpool
        data = await file.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES: raise ValueError('文件超过 50 MB 上限。')
        return await run_in_threadpool(knowledge.register, file.filename or 'source.txt', data, company, period, original_document_id or None)
    @app.get('/v1/documents/{ident}/original')
    def original(ident: str):
        path, doc = knowledge.source_path(ident)
        return FileResponse(path, filename=doc['name'], media_type='application/pdf' if doc['suffix'] == '.pdf' else 'application/octet-stream', content_disposition_type='inline' if doc['suffix'] == '.pdf' else 'attachment')
    @app.get('/v1/documents/{ident}/view', response_class=HTMLResponse)
    def source_view(ident: str):
        doc = store.get('document', ident)
        snapshot = knowledge.parsed(ident)
        blocks = ''.join('<section id="' + esc(p['parent_id']) + '"><h2>' + esc(p['parent_id']) + (' · 第 ' + str(p['source_locator']['page']) + ' 页' if p['source_locator'].get('page') else '') + '</h2><pre>' + esc(p['parent_text']) + '</pre><small>SHA256 ' + esc(p['source_hash']) + '</small></section>' for p in snapshot['parents'])
        return '<!doctype html><meta charset="utf-8"><title>' + esc(doc['name']) + '</title><style>body{font:15px/1.8 system-ui;max-width:1000px;margin:40px auto;padding:20px;color:#253e54}pre{white-space:pre-wrap;overflow-wrap:anywhere}section{border-top:1px solid #ccc;padding:24px 0}section:target{background:#fff5cd}small{overflow-wrap:anywhere}h2{font-size:18px}</style><h1>' + esc(doc['name']) + '</h1><p><a href="/v1/documents/' + esc(ident) + '/original">下载原始文件</a> · 原件 SHA256 ' + esc(doc['sha256']) + '</p>' + blocks
    @app.get('/v1/knowledge-bases')
    def kbs(): return store.list('kb')
    @app.get('/v1/knowledge-bases/builds')
    def builds(): return store.list('build')
    @app.post('/v1/knowledge-bases/builds')
    def create_build(payload: dict[str, Any]): return knowledge.create(payload)
    @app.get('/v1/knowledge-bases/builds/{ident}')
    def get_build(ident: str): return store.get('build', ident)
    @app.post('/v1/knowledge-bases/builds/{ident}/cancel')
    def cancel_build(ident: str):
        with store.lock:
            record = store.get('build', ident)
            if record['status'] in {'READY', 'FAILED', 'CANCELLED'}: raise ConflictError('此建库状态不能取消。')
            record['status'] = 'CANCELLED'
            store.save('build', ident, record)
            store.append(ident, 'cancelled', {})
            return record
    @app.get('/v1/knowledge-bases/{kb_id}/versions')
    def versions(kb_id: str): return [r for r in store.list('build') if r['kb_id'] == kb_id and r['status'] == 'READY']
    @app.post('/v1/knowledge-bases/{kb_id}/search')
    def search(kb_id: str, payload: dict[str, Any]):
        version = payload.get('kb_version') or store.get('kb', kb_id)['active_version']
        if knowledge.snapshot(version)['kb_id'] != kb_id: raise ValueError('知识库与版本不匹配。')
        ident = 'SEARCH-' + hashlib.sha256(os.urandom(32)).hexdigest()[:12]
        hits = knowledge.retrieve(version, payload.get('query') or payload, payload.get('source_scope'), ident)
        return {'kb_id': kb_id, 'kb_version': version, 'hits': hits, 'audit_job': ident}

    @app.get('/v1/reviews')
    def review_list(): return reviews.list()
    @app.post('/v1/reviews', status_code=202)
    def create_review(payload: dict[str, Any]): return reviews.create(payload)
    @app.get('/v1/reviews/{ident}')
    def get_review(ident: str): return reviews.get(ident)
    @app.post('/v1/reviews/{ident}/cancel')
    def cancel_review(ident: str): return reviews.cancel(ident)
    @app.post('/v1/reviews/{ident}/continue')
    def continue_review(ident: str): return reviews.continue_review(ident)
    @app.post('/v1/reviews/{ident}/supplement')
    def supplement(ident: str, payload: dict[str, Any]): return reviews.supplement(ident, payload)
    @app.get('/v1/human-tasks')
    def human_tasks(): return reviews.human_tasks()
    @app.post('/v1/human-tasks/{ident}/decision')
    def human_decision(ident: str, payload: dict[str, Any]): return reviews.submit_human_decision(ident, payload)
    @app.get('/v1/rules')
    def rules():
        return {'version': 'credit-review-workbench-v1', 'rules': [{'rule_id': r.rule_id, 'version': r.version, 'issue_type': r.issue_type, 'severity': r.severity, 'explanation': r.explanation} for r in default_rules()],
                'human_policy': ['证据不足', '证据冲突', '低置信度', '重要信贷风险', '高风险业务规则'], 'numeric_policy': 'Decimal 运算；操作数须匹配证据原文、单位和期间。'}
    @app.get('/v1/audit/{job}')
    def audit(job: str): return {'job': job, 'integrity': store.verify(job), 'papers': store.papers(job)}
    @app.get('/v1/audit/{job}/download')
    def download_papers(job: str):
        store.append(job, 'working_papers_exported', {'format': 'zip'}, 'local-reviewer')
        return Response(bundle(store, knowledge, job), media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="' + job + '-working-papers.zip"'})
    @app.get('/v1/reviews/{ident}/export/{format}')
    def export(ident: str, format: str, request: Request):
        record = reviews.get(ident)
        if format not in {'pdf', 'html', 'json', 'zip', 'csv'}: raise ValueError('支持 pdf / html / json / zip / csv。')
        store.append(ident, 'review_report_exported', {'format': format, 'status': record['status']}, 'local-reviewer')
        base = str(request.base_url).rstrip('/')
        if format == 'pdf': data, mime = pdf_report(record, base), 'application/pdf'
        elif format == 'csv': data, mime = csv_report(record), 'text/csv; charset=utf-8'
        elif format == 'html': data, mime = html_report(record, base), 'text/html; charset=utf-8'
        elif format == 'zip': data, mime = bundle(store, knowledge, ident), 'application/zip'
        else: data, mime = encode(record).encode(), 'application/json'
        return Response(data, media_type=mime, headers={'Content-Disposition': 'attachment; filename="' + ident + '-review.' + format + '"'})

    frontend = PROJECT / 'frontend'
    app.mount('/assets', StaticFiles(directory=frontend), name='assets')
    @app.get('/{path:path}', include_in_schema=False)
    def frontend_page(path: str):
        if path.startswith(('v1/', 'health/')): raise HTTPException(status_code=404, detail='接口不存在。')
        file = (frontend / path).resolve()
        if file.is_file() and frontend.resolve() in file.parents: return FileResponse(file)
        return FileResponse(frontend / 'index.html')
    return app
