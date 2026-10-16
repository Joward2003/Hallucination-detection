"""Inert original-DOM snapshots: retain layout, localize assets, locate actual text.

Original response bytes remain untouched. Only our hash-authorized locator script
runs in an opaque-origin sandbox; remote scripts and network access are disabled.
"""
from __future__ import annotations
import base64, hashlib, html, json, re, threading
from urllib.parse import urljoin, urlsplit
from pathlib import Path
from bs4 import BeautifulSoup
from .web_sources import fetch_public, canonical_url, parse_html
from .storage import now

_lock=threading.Lock()
SCRIPT=r'''(()=>{
const cfg=JSON.parse(document.getElementById('review-location').textContent);
const target=cfg.target?document.querySelector('[data-review-target="'+CSS.escape(cfg.target)+'"]'):null;
const normalized=t=>t.replace(/\s/g,'').toLowerCase();
function highlight(root,term,kind){
 if(!root||!term)return 0;
 const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT,{acceptNode:n=>n.parentElement.closest('script,style,mark,[data-review-toolbar]')?NodeFilter.FILTER_REJECT:NodeFilter.FILTER_ACCEPT});
 const nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);
 let chars='',map=[];
 for(const node of nodes){for(let i=0;i<node.textContent.length;i++){const c=node.textContent[i];if(/\s/.test(c))continue;chars+=c.toLowerCase();map.push([node,i]);}}
 const wanted=normalized(term);if(!wanted)return 0;
 const ranges=[];let from=0;while(from<chars.length){const i=chars.indexOf(wanted,from);if(i<0)break;ranges.push([i,i+wanted.length]);from=i+wanted.length;if(ranges.length>=60)break;}
 for(const [a,b] of ranges.reverse()){
  const groups=new Map();for(let i=a;i<b;i++){const p=map[i];if(p){const g=groups.get(p[0]);if(g)g[1]=p[1]+1;else groups.set(p[0],[p[1],p[1]+1]);}}
  for(const [node,[start,end]] of [...groups].reverse()){if(!node.isConnected||node.parentElement.closest('mark'))continue;const range=document.createRange();range.setStart(node,start);range.setEnd(node,end);const mark=document.createElement('mark');mark.className='review-'+kind;range.surroundContents(mark);}
 }
 return ranges.length;
}
let cited=highlight(target||document.body,cfg.quote,'citation');
if(!cited&&target)cited=highlight(document.body,cfg.quote,'citation');
const found=highlight(document.body,cfg.keyword,'keyword');
if((cfg.keyword&&!found)|| (cfg.quote&&!cited)){
 const note=document.createElement('p');note.dataset.reviewToolbar='true';note.textContent='部分定位文字未在原页匹配，请核对原件。';note.style.cssText='position:fixed;bottom:8px;right:8px;z-index:99999;background:#fff5e5;color:#663c0b;padding:8px 12px;font:13px sans-serif;max-width:300px';document.body.append(note);
}
const locate=()=>{const mark=document.querySelector('mark.review-keyword')||document.querySelector('mark.review-citation')||target;if(mark)window.scrollTo({top:Math.max(0,mark.getBoundingClientRect().top+window.scrollY-window.innerHeight/3),behavior:'instant'});};
window.addEventListener('load',locate,{once:true});locate();
})();'''
SCRIPT_HASH=base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
CSP="default-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; script-src 'sha256-"+SCRIPT_HASH+"'; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"


def ensure_original(knowledge,ident,fetcher=fetch_public):
    path,doc=knowledge.source_path(ident)
    if doc.get('source_type')!='web':raise ValueError('此来源不是网页。')
    directory=path.parent/'original-view';directory.mkdir(exist_ok=True)
    with _lock:
        cached=directory/'manifest.json'
        if cached.exists() and json.loads(cached.read_text()).get('renderer')=='inert-original-dom-v3':
            manifest=json.loads(cached.read_text());body=(directory/'page.html').read_bytes()
            if hashlib.sha256(body).hexdigest()!=manifest['html_sha256']:raise ValueError('网页原貌快照完整性校验失败。')
            return body.decode(),manifest
        soup=BeautifulSoup(path.read_bytes(),'html.parser')
        snapshot=knowledge.parsed(ident)
        locators=doc.get('block_locators') or parse_html(path.read_bytes())[1]['block_locators']
        targets={}
        for parent in snapshot['parents']:
            for block in parent['source_locator'].get('block_id','').split('+'):
                selector=locators.get(block)
                node=soup.select_one(selector) if selector else None
                if node:
                    anchor='review-'+parent['parent_id'];node['data-review-target']=anchor;targets[parent['parent_id']]=anchor
                    break
        base=doc.get('final_url') or doc.get('requested_url');assets={};failures=[];total=0
        def asset(url,depth=0,defer=False):
            nonlocal total
            if not url or url.startswith('data:'):return url or ''
            absolute=urljoin(base,url)
            try:absolute=canonical_url(absolute)
            except ValueError:return ''
            previous=assets.get(absolute)
            if previous and (defer or previous['status']!='pending'):return '/v1/documents/'+ident+'/web-assets/'+previous['name'] if previous['status'] in {'ready','pending','fetching'} else ''
            if sum(a['status']=='ready' for a in assets.values())>=20 or (not previous and len(assets)>=250) or total>=8*1024*1024 or depth>2:return ''
            name=hashlib.sha256(absolute.encode()).hexdigest()[:24]
            # Queue dependencies so one stylesheet's fonts cannot crowd out later stylesheets.
            assets[absolute]={'name':name,'status':'pending' if defer else 'fetching','depth':depth}
            if defer:return '/v1/documents/'+ident+'/web-assets/'+name
            try:
                result=fetcher(absolute,timeout=8,kind='asset',max_bytes=2*1024*1024)
                data=result['content'];mime=result['content_type'].split(';')[0]
                if 'css' in mime or urlsplit(absolute).path.endswith('.css'):
                    css=data.decode('utf-8',errors='replace')
                    def css_url(m):
                        value=m.group(1).strip().strip('\"\'');return 'url("'+asset(urljoin(absolute,value),depth+1,defer=True)+'")'
                    css=re.sub(r'url\(\s*([^)]*)\)',css_url,css,flags=re.I)
                    css=re.sub(r'@import\s+[\"\']([^\"\']+)[\"\']',lambda m:'@import url("'+asset(urljoin(absolute,m[1]),depth+1,defer=True)+'")',css,flags=re.I)
                    data=css.encode();mime='text/css'
                total+=len(data);(directory/name).write_bytes(data)
                assets[absolute].update(status='ready',sha256=hashlib.sha256(data).hexdigest(),bytes=len(data),mime=mime)
                return '/v1/documents/'+ident+'/web-assets/'+name
            except Exception as exc:
                assets[absolute].update(status='failed',error=type(exc).__name__);failures.append({'url':absolute,'error':str(exc)});return ''
        for node in soup.select('script,iframe,object,embed,base,form,meta[http-equiv],audio,video,source,template'):
            node.decompose()
        for node in soup.find_all(True):
            for attr in list(node.attrs):
                if attr.lower().startswith('on') or attr.lower() in {'srcdoc','action','formaction','autofocus','integrity','nonce','ping','srcset'}:del node.attrs[attr]
            if node.name=='link':
                if 'stylesheet' in node.get('rel',[]):
                    local=asset(node.get('href'));node['href']=local
                    if not local:node.decompose()
                else:node.decompose()
            elif node.name=='img':
                node['src']=asset(node.get('src'),defer=True);node['loading']='eager'
            elif node.name=='a' and node.get('href'):
                href=node['href']
                if not href.startswith('#'):
                    try:node['href']=canonical_url(urljoin(base,href));node['target']='_blank';node['rel']='noopener noreferrer'
                    except ValueError:del node['href']
            elif node.name not in {'html','body','head','style'}:
                for attr in ['src','href','xlink:href','background']:
                    if attr in node.attrs and node.name!='img':del node.attrs[attr]
        # Inline CSS resources also pass the same bounded, public-only fetcher.
        for node in soup.find_all('style'):
            css=node.get_text();node.string=re.sub(r'url\(\s*([^)]*)\)',lambda m:'url("'+asset(m[1].strip().strip('\"\''),defer=True)+'")',css,flags=re.I)
        while sum(a['status']=='ready' for a in assets.values())<20 and total<8*1024*1024:
            pending=[(u,a) for u,a in assets.items() if a['status']=='pending']
            if not pending:break
            # CSS imports first, then visible images, finally fonts and legacy formats.
            pending.sort(key=lambda pair:0 if '.css' in urlsplit(pair[0]).path else 2 if re.search(r'\.(?:woff2?|ttf|eot)$',urlsplit(pair[0]).path) else 1)
            url,item=pending[0];asset(url,item['depth'])
        for item in assets.values():
            if item['status']=='pending':item.update(status='omitted',reason='资源数量或大小预算已用尽。')
        body=str(soup)
        manifest={'document_id':ident,'original_sha256':doc['sha256'],'created_at':now(),'renderer':'inert-original-dom-v3','targets':targets,'assets':assets,'asset_failures':failures,'boundary':'原始DOM与可取得样式；禁用原站脚本、表单与外部网络，动态内容可能缺失。'}
        (directory/'page.html').write_text(body)
        manifest['html_sha256']=hashlib.sha256(body.encode()).hexdigest()
        cached.write_text(json.dumps(manifest,ensure_ascii=False))
        knowledge.store.append(ident,'original_dom_snapshot_built',manifest)
        return body,manifest


def original_html(knowledge,ident,quote='',keyword='',parent=''):
    page,manifest=ensure_original(knowledge,ident)
    context=json.dumps({'target':manifest['targets'].get(parent,''),'quote':quote[:2000],'keyword':keyword[:200]},ensure_ascii=False).replace('<','\\u003c')
    additions='<style>mark.review-citation{background:#d5eee7!important;color:#172e40!important;outline:2px solid #136f68}mark.review-keyword{background:#ffe5a0!important;color:#172e40!important}[data-review-target]{scroll-margin:24px}</style><script id="review-location" type="application/json">'+context+'</script><script>'+SCRIPT+'</script>'
    return page.replace('</body>',additions+'</body>') if '</body>' in page else page+additions


def asset_path(knowledge,ident,name):
    if not re.fullmatch(r'[a-f0-9]{24}',name):raise ValueError('资源名称无效。')
    path,_=knowledge.source_path(ident);directory=path.parent/'original-view'
    manifest=json.loads((directory/'manifest.json').read_text())
    item=next((a for a in manifest['assets'].values() if a['name']==name and a['status']=='ready'),None)
    if not item:raise KeyError(name)
    asset=directory/name
    if hashlib.sha256(asset.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('来源资源完整性校验失败。')
    return asset,item['mime']
