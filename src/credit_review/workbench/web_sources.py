"""Bounded public-web capture. Source HTML is data, never executable UI."""
from __future__ import annotations
import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit, urljoin, parse_qsl, urlencode

from bs4 import BeautifulSoup

MAX_WEB_BYTES = 12 * 1024 * 1024
TRACKING = {'fbclid', 'gclid', 'msockid'}
URL_RE = re.compile(r'https?://[^\s<>\]\)"\u3002\uff0c]+')


def canonical_url(url):
    parts = urlsplit(str(url).strip())
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.port not in {None, 443}:
        raise ValueError('来源网址须为不含凭据的标准 HTTPS 公网地址。')
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith('utm_') and k.lower() not in TRACKING]
    return urlunsplit(('https', parts.netloc.lower(), parts.path or '/', urlencode(query), ''))


def report_urls(text):
    return list(dict.fromkeys(canonical_url(m.group().rstrip('.,;；')) for m in URL_RE.finditer(text)))[:20]


def fetch_public(url, timeout=20, *, kind='source', max_bytes=MAX_WEB_BYTES):
    """Validate each redirect, pin a public IP, retain hostname TLS verification.

    No proxy environment, local cookies, model credentials, or browser session
    are forwarded to report-supplied URLs.
    """
    requested = canonical_url(url)
    current, redirects = requested, []
    for _ in range(6):
        parts = urlsplit(current)
        addresses = socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError('网址解析到非公网地址，已拒绝读取。')
        address = addresses[0][4][0]
        class PinnedConnection(http.client.HTTPSConnection):
            def connect(self):
                sock = socket.create_connection((address, 443), timeout=self.timeout)
                self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        connection = PinnedConnection(parts.hostname, timeout=timeout, context=ssl.create_default_context())
        try:
            connection.request('GET', urlunsplit(('', '', parts.path or '/', parts.query, '')),
                               headers={'User-Agent': 'CreditReviewWorkbench/0.3 (public source verification)', 'Accept-Encoding': 'identity'})
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader('Location')
                if not location: raise ValueError('来源重定向缺少目标。')
                next_url = canonical_url(urljoin(current, location))
                redirects.append({'from': current, 'to': next_url, 'status': response.status})
                current = next_url
                continue
            if response.status != 200:
                raise ValueError(f'来源服务器返回 HTTP {response.status}；未取得正文。')
            if int(response.getheader('Content-Length') or 0) > max_bytes:
                raise ValueError('网页或关联文件超过 12 MB 读取上限。')
            content = response.read(max_bytes + 1)
            if len(content) > max_bytes: raise ValueError('来源内容超过读取上限。')
            mime = response.getheader('Content-Type', '').lower()
            accepted=('html' in mime or 'pdf' in mime or content.startswith(b'%PDF')) if kind=='source' else ('html' in mime or 'xml' in mime or 'text/plain' in mime) if kind=='search' else (mime.startswith(('text/css','image/','font/','application/font','application/x-font','application/octet-stream')) or mime.startswith('text/plain'))
            if not accepted:
                raise ValueError('网址未返回 HTML 或 PDF。')
            return {'requested_url': requested, 'final_url': current, 'redirects': redirects,
                    'content': content, 'content_type': mime, 'http_status': 200,
                    'last_modified_header': response.getheader('Last-Modified')}
        finally:
            connection.close()
    raise ValueError('来源重定向次数过多。')


MONTHS = {name.lower(): i for i, name in enumerate(('January','February','March','April','May','June','July','August','September','October','November','December'), 1)}


def dates_in(text):
    result = []
    for m in re.finditer(r'((?:19|20)\d{2})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})\s*日?', text):
        try: result.append((datetime(*map(int, m.groups())).date().isoformat(), m.group()))
        except ValueError: pass
    for m in re.finditer(r'('+'|'.join(MONTHS)+r')\s+(\d{1,2}),?\s+((?:19|20)\d{2})', text, re.I):
        try: result.append((datetime(int(m[3]), MONTHS[m[1].lower()], int(m[2])).date().isoformat(), m.group()))
        except ValueError: pass
    return result


def period_labels(text):
    result = []
    for m in re.finditer(r'(?:FY\s*(20\d{2}|\d{2})\s*[- ]?Q([1-4])|((?:19|20)\d{2})\s*财年\s*第([一二三四1-4])季度)', text, re.I):
        year = m[1] or m[3]
        if len(year) == 2: year = '20'+year
        quarter = m[2] or (str('一二三四'.find(m[4])+1) if m[4] in '一二三四' else m[4])
        result.append(f'FY{year}Q{quarter}')
    return list(dict.fromkeys(result))


def parse_html(raw):
    soup = BeautifulSoup(raw, 'html.parser')
    title = soup.title.get_text(' ', strip=True) if soup.title else ''
    metadata = {'block_locators':{}, 'title': title, 'published_at': None, 'updated_at': None, 'date_evidence': {}, 'publisher': None}
    for field, names in [('published_at', {'article:published_time','datepublished','date','pubdate'}), ('updated_at', {'article:modified_time','datemodified','last-modified'})]:
        for node in soup.find_all('meta'):
            if str(node.get('property') or node.get('name') or '').lower() in names:
                value = node.get('content') or ''
                dates = dates_in(value)
                if dates:
                    metadata[field] = dates[0][0]
                    metadata['date_evidence'][field] = {'method': 'html_meta', 'quote': str(node)[:1500]}
                    break
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            value = json.loads(script.string or '{}')
            candidates = value if isinstance(value, list) else [value] + (value.get('@graph', []) if isinstance(value, dict) else [])
            for candidate in candidates:
                if not isinstance(candidate, dict): continue
                for field, key in [('published_at','datePublished'), ('updated_at','dateModified')]:
                    if not metadata[field] and dates_in(str(candidate.get(key, ''))):
                        metadata[field] = dates_in(candidate[key])[0][0]
                        metadata['date_evidence'][field] = {'method':'jsonld','quote':str(candidate[key])}
                publisher = candidate.get('publisher')
                if isinstance(publisher, dict): metadata['publisher'] = publisher.get('name')
        except (ValueError, TypeError): pass
    # Locators are recorded against the untouched original DOM, before removal
    # of navigation or active content changes sibling positions.
    for node in soup.find_all(['h1','h2','h3','h4','h5','h6','p','li','table','time','div']):
        parts=[];ancestor=node
        while ancestor and ancestor.name and ancestor.name!='[document]':
            siblings=[n for n in ancestor.parent.find_all(ancestor.name,recursive=False)] if ancestor.parent else [ancestor]
            position=next((i+1 for i,n in enumerate(siblings) if n is ancestor),1)
            parts.append(ancestor.name+':nth-of-type('+str(position)+')');ancestor=ancestor.parent
        node['data-review-locator']=' > '.join(reversed(parts))
    for node in soup.select('script,style,noscript,iframe,object,embed,nav,footer,header,form,button,svg,canvas'):
        node.decompose()
    root = soup.find('article') or soup.find('main') or soup.body or soup
    labels = period_labels(title)
    current_period = labels[0] if len(labels) == 1 else None
    current_end = None
    current_period_evidence = title if current_period else None
    current_end_evidence = None
    blocks, temporal = [], {}
    for node in root.find_all(['h1','h2','h3','h4','h5','h6','p','li','table','time','div']):
        if node.find_parent('table') or node.name == 'p' and node.find_parent('li'): continue
        if node.name=='div' and node.find(['div','p','li','table','h1','h2','h3','h4','h5','h6','time']): continue
        text = re.sub(r'\s+', ' ', node.get_text(' ', strip=True)).strip()
        if not text: continue
        explicit = period_labels(text)
        if len(explicit) == 1:
            current_period = explicit[0]
            current_period_evidence = text
        dates = dates_in(text)
        end_clause = re.search(r'(?:(?:quarter|(?:fiscal )?year) ended|截至|截止)\s*(.*)',text,re.I)
        if end_clause:
            end_dates=dates_in(end_clause[1])
            if end_dates:
                current_end=end_dates[0][0]
                current_end_evidence=text
        if re.search(r'(?:fiscal year|year) ended', text, re.I) and current_period:
            current_period = current_period[:6]
            current_period_evidence = text
        if not metadata['published_at'] and dates and (re.search(r'\b(?:Wash|CUPERTINO|REDMOND)\b|发布|PRESS RELEASE', text, re.I) or node.name == 'time'):
            metadata['published_at'] = dates[0][0]
            metadata['date_evidence']['published_at'] = {'method':'source_text','quote':text[:1200]}
        ident = f'WEB{len(blocks)+1:05d}'
        metadata['block_locators'][ident]=node.get('data-review-locator')
        if node.name == 'table':
            node.attrs = {}
            for descendant in node.find_all(True):
                if descendant.name not in {'table','thead','tbody','tfoot','tr','td','th','p','br','b','strong','span'}:
                    descendant.unwrap(); continue
                descendant.attrs = {k: str(v) for k,v in descendant.attrs.items() if k in {'rowspan','colspan'} and str(v).isdigit() and 0 < int(v) <= 50}
            content = str(node)
        else: content = text
        block = {'id':ident, 'type':'table' if node.name=='table' else 'text', 'text':content}
        if node.name.startswith('h') and node.name[1:].isdigit(): block['text_level'] = int(node.name[1])
        blocks.append(block)
        years = sorted(set(re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)', text)))
        temporal[ident] = {'data_period': explicit[0] if len(explicit)==1 else current_period,
                           'data_period_end': current_end, 'mentioned_years': years,
                           'ambiguous_period': len(years)>1 or len(explicit)>1,
                           'period_basis': 'source_heading_or_statement' if current_period else 'unknown',
                           'period_evidence': (current_period_evidence or '')[:1200],
                           'data_period_end_evidence': (current_end_evidence or '')[:1200]}
    if not blocks or sum(len(b['text']) for b in blocks) < 80:
        raise ValueError('网页未取得足够正文，可能需要登录或动态加载；没有生成替代内容。')
    metadata['block_temporal'] = temporal
    return blocks, metadata
