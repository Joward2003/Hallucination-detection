"""Safe standalone snapshot reader with stable parent anchors and highlights."""
import html
import re
from bs4 import BeautifulSoup, NavigableString


def highlighted(content, quote='', keyword=''):
    soup = BeautifulSoup(content if '<table' in content.lower() else '<p>'+html.escape(content)+'</p>', 'html.parser')
    terms = []
    for value, kind in [(quote,'citation'), (keyword,'keyword')]:
        text = BeautifulSoup(value,'html.parser').get_text(' ',strip=True) if '<' in value else value
        if text.strip(): terms.append((text.strip(),kind))
    # Match literal text only. No source scripts, resource URLs or event attributes.
    for node in list(soup.find_all(string=True)):
        raw = str(node)
        ranges = []
        for term, kind in terms:
            for match in re.finditer(re.escape(term),raw,re.I): ranges.append((match.start(),match.end(),kind))
        if not ranges: continue
        pieces, offset = [], 0
        for start,end,kind in sorted(ranges):
            if start<offset: continue
            pieces.append(NavigableString(raw[offset:start]))
            mark=soup.new_tag('mark');mark['class']=kind;mark.string=raw[start:end];pieces.append(mark);offset=end
        pieces.append(NavigableString(raw[offset:]))
        for piece in pieces:node.insert_before(piece)
        node.extract()
    return str(soup)


def snapshot_html(doc, snapshot, quote='', keyword='', focus=''):
    sections=[]
    parents=snapshot['parents']
    if focus:
        index=next((i for i,p in enumerate(parents) if p['parent_id']==focus),None)
        if index is None:raise ValueError('网页定位段落不存在。')
        parents=parents[max(0,index-1):index+2]
    for parent in parents:
        content=parent['parent_text']
        if '<table' in content.lower():
            soup=BeautifulSoup(content,'html.parser')
            for tag in list(soup.find_all(True)):
                if tag.name in {'script','style','iframe','object','embed','img'}:tag.decompose();continue
                if tag.name not in {'table','thead','tbody','tfoot','tr','td','th','p','br','b','strong','span'}:tag.unwrap();continue
                tag.attrs={k:str(v) for k,v in tag.attrs.items() if k in {'rowspan','colspan'} and str(v).isdigit() and 0<int(v)<=50}
            content=str(soup)
        sections.append('<section id="'+html.escape(parent['parent_id'])+'"><small>'+html.escape(parent['parent_id'])+'</small>'+highlighted(content,quote,keyword)+'</section>')
    original = doc.get('final_url')
    link='<a href="'+html.escape(original,quote=True)+'" target="_blank" rel="noopener noreferrer">打开当前原网页</a>' if original else ''
    if focus:
        link+=' · <a href="/v1/documents/'+html.escape(doc['document_id'],quote=True)+'/view#'+html.escape(focus,quote=True)+'">查看完整保存快照</a>'
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; style-src &#39;unsafe-inline&#39;; base-uri &#39;none&#39;; form-action &#39;none&#39;">'
        '<title>'+html.escape(doc['name'])+'</title><style>body{font:15px/1.8 system-ui;margin:24px;color:#243746;background:white;overflow-wrap:anywhere}h1{font-size:21px}section{border-top:1px solid #dce3e8;padding:16px 0;scroll-margin-top:12px}section:target{background:#f0f7f5}p{white-space:pre-wrap}table{border-collapse:collapse;display:block;overflow:auto;max-width:100%}td,th{border:1px solid #dce3e8;padding:8px}small{color:#607180}mark.citation{background:#d5eee7}mark.keyword{background:#ffe5a0}</style>'
        '<h1>'+html.escape(doc['name'])+'</h1><p>'+link+'</p><p><small>抓取：'+html.escape(str(doc.get('fetched_at') or '未记录'))+' · 发布：'+html.escape(str(doc.get('published_at') or '未知'))+'<br>SHA256 '+html.escape(doc['sha256'])+'</small></p>'
        '<p><small>'+('当前展示定位段落及相邻上下文。' if focus else '')+'绿色为匹配到的引用原文，黄色为关键词；高亮不表示证据支持结论。</small></p>'+''.join(sections)+'</html>')
