"""Bounded public search followed by real source capture, never snippet-as-proof."""
from __future__ import annotations
import re
from urllib.parse import urlencode, urlsplit, parse_qs
from bs4 import BeautifulSoup
from .web_sources import fetch_public, canonical_url
from .knowledge import BoundRetriever
from .storage import now


def public_search(query,fetcher=fetch_public):
    query=str(query).strip()
    if not 2<=len(query)<=400:raise ValueError('公开检索词须为2至400字符。')
    errors=[]
    providers=[('bing_rss','https://www.bing.com/search?'+urlencode({'q':query,'format':'rss'})),
               ('bing_html','https://www.bing.com/search?'+urlencode({'q':query,'setlang':'en-US','cc':'us'})),
               ('duckduckgo_html','https://html.duckduckgo.com/html/?'+urlencode({'q':query}))]
    for provider,url in providers:
        try:
            response=fetcher(url,timeout=12,kind='search',max_bytes=2*1024*1024)
            raw=response['content'];soup=BeautifulSoup(raw,'xml' if provider=='bing_rss' else 'html.parser') if provider!='bing_rss' else None
            results=[]
            if provider=='bing_rss':
                from xml.etree import ElementTree as ET
                root=ET.fromstring(raw)
                for item in root.findall('.//item'):
                    results.append({'title':item.findtext('title') or '', 'url':item.findtext('link') or '', 'snippet':item.findtext('description') or ''})
            else:
                for anchor in soup.select('li.b_algo h2 a' if provider=='bing_html' else 'a.result__a'):
                    link=anchor.get('href','');parts=urlsplit(link)
                    if 'duckduckgo.com' in parts.netloc:link=parse_qs(parts.query).get('uddg',[link])[0]
                    results.append({'title':anchor.get_text(' ',strip=True),'url':link,'snippet':''})
            valid=[];seen=set()
            for result in results:
                try:target=canonical_url(result['url'])
                except ValueError:continue
                if target in seen:continue
                seen.add(target);valid.append({**result,'url':target})
            terms={t.lower() for t in re.findall(r'[A-Za-z]{3,}|[\u4e00-\u9fff]{2,}',query)}-{'site','com','www','https','microsoft','apple','official'}
            if terms:
                relevant=[r for r in valid if any(t in (r['title']+' '+r['snippet']+' '+r['url']).lower() for t in terms)]
                if not relevant:
                    errors.append({'provider':provider,'error':'搜索接口返回了页面，但没有匹配到关键词对应的内容，未作为证据采集。'})
                    continue
                valid=relevant
            if valid:return {'provider':provider,'query':query,'search_url':url,'results':valid[:6],'failures':errors,'searched_at':now()}
            errors.append({'provider':provider,'error':'未返回可用结果，可能受访问限制或需要交互验证。'})
        except Exception as exc:errors.append({'provider':provider,'error':str(exc)})
    return {'query':query,'results':[],'failures':errors,'searched_at':now(),'status':'unavailable'}


class BrowserRetriever:
    def __init__(self,knowledge,record,searcher=public_search):
        self.knowledge=knowledge;self.store=knowledge.store;self.job=record['review_id'];self.searcher=searcher
        self.bound=BoundRetriever(knowledge,record['kb_version'],record['source_scope'],self.job)
        self.searched=set()

    def retrieve(self,query):
        record=self.store.get('review',self.job)
        query=dict(query)
        # The LLM chooses the short public query; the full private report is
        # never submitted to a search engine.
        web_query=query.get('web_query')
        if record.get('web_search_enabled') and web_query and web_query not in self.searched:
            self.searched.add(web_query)
            searches=record.get('web_searches',[])
            if len(searches)<record.get('web_search_budget',12):
                result=self.searcher(web_query)
                self.store.append(self.job,'browser_public_search',{**result,'claim_id':query.get('fact_id'),'route':query.get('source_route'),'note':'搜索摘要仅供发现网址，不作为核验证据。'})
                searches.append({'query':web_query,'provider':result.get('provider'),'result_count':len(result['results'])})
                added=[]
                hosts=query.get('preferred_domains') or []
                candidates=sorted(result['results'],key=lambda r:not any((urlsplit(r['url']).hostname or '').endswith(h) for h in hosts))
                known=set(record['source_scope'].get('allowed_document_ids',[]))
                for item in candidates[:2]:
                    if len(record.get('web_discovered_document_ids',[]))+len(added)>=12:break
                    try:
                        doc=self.knowledge.capture_url(item['url'],job=self.job)
                        if doc['status']=='READY' and doc['document_id'] not in known:
                            added.append(doc['document_id']);known.add(doc['document_id'])
                    except Exception as exc:self.store.append(self.job,'browser_result_capture_failed',{'url':item['url'],'error':str(exc)})
                # Check cancellation again before publishing a newer round.
                current=self.store.get('review',self.job)
                if current['status']=='CANCELLED':raise InterruptedError('任务已取消')
                current['web_searches']=searches
                if added:
                    build=self.knowledge.create({'kb_id':'search-'+self.job[2:18],'name':record['report_name']+' · 检索轮次','document_ids':sorted(known)},synchronous=True)
                    if build['status']!='READY':raise ValueError('公开来源索引失败：'+str(build.get('error')))
                    current.setdefault('source_version_history',[]).append({'previous':current['kb_version'],'version':build['version'],'query_id':query.get('query_id'),'new_documents':added,'at':now()})
                    current['kb_version']=build['version'];current['source_scope'].update(allowed_document_ids=sorted(known),corpus_version=build['version'])
                    current.setdefault('web_discovered_document_ids',[]).extend(added)
                    self.store.append(self.job,'search_round_sources_pinned',current['source_version_history'][-1])
                self.store.save('review',self.job,current)
                record=current
        self.bound.version=record['kb_version'];self.bound.scope=record['source_scope']
        hits=self.bound.retrieve(query)
        for hit in hits:hit['retrieved_kb_version']=record['kb_version']
        return hits
