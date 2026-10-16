// Evidence is untrusted document content. Rebuild allowed structure; never insert
// the source HTML into the live document or retain source attributes/URLs.
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const blocked = new Set(['SCRIPT','STYLE','IFRAME','OBJECT','EMBED','SVG','MATH','IMG','LINK','META','BASE','FORM','INPUT','BUTTON','VIDEO','AUDIO','SOURCE']);
const blocks = new Set(['P','DIV','SECTION','ARTICLE','H1','H2','H3','H4','H5','H6','LI']);

function fragment(html, tableFragment = false) {
  const template = document.createElement('template');
  template.innerHTML = tableFragment ? '<table><tbody><tr>'+html+'</tr></tbody></table>' : html;
  return template.content;
}
function textOf(node) {
  if (node.nodeType === 3) return node.nodeValue || '';
  if (blocked.has(node.nodeName)) return '';
  if (node.nodeName === 'BR') return '\n';
  const text = [...node.childNodes].map(textOf).join('');
  return blocks.has(node.nodeName) ? text+'\n' : text;
}
function normalized(text) {
  let value = ''; const positions = [];
  for (let i=0; i<text.length; i++) {
    if (/\s/.test(text[i])) continue;
    value += text[i].toLowerCase(); positions.push(i);
  }
  return {value,positions};
}
export function highlightEvidenceText(text, terms = []) {
  text=String(text ?? '');
  const {value,positions}=normalized(text), intervals=[];
  for (const term of terms) {
    const needle=normalized(String(term)).value;
    if (needle.length<2) continue;
    let from=0, at;
    while ((at=value.indexOf(needle,from))!==-1) {
      intervals.push([positions[at],positions[at+needle.length-1]+1]);
      from=at+needle.length;
    }
  }
  intervals.sort((a,b)=>a[0]-b[0]);
  const merged=[];
  for(const span of intervals){
    const last=merged[merged.length-1];
    if(last && span[0]<=last[1])last[1]=Math.max(last[1],span[1]);else merged.push([...span]);
  }
  let cursor=0,html='';
  for(const [start,end] of merged){html+=escape(text.slice(cursor,start))+'<mark class="evidence-highlight">'+escape(text.slice(start,end))+'</mark>';cursor=end;}
  return html+escape(text.slice(cursor));
}
function quoteTerms(quote) {
  if(!quote)return [];
  const root=fragment(String(quote), /<\/?(?:td|th|tr)\b/i.test(quote) && !/<table\b/i.test(quote));
  const cells=[...root.querySelectorAll('td,th')];
  return [...new Set((cells.length?cells.map(textOf):[textOf(root)]).map(t=>t.trim()).filter(t=>normalized(t).value.length>=2))].slice(0,80);
}
function spans(cell) {
  return ['rowspan','colspan'].map(key=>{
    const raw=cell.getAttribute(key) || '';
    const value=/^\d{1,3}$/.test(raw)?Number(raw):1;
    return value>1 && value<=100 ? ' '+key+'="'+value+'"' : '';
  }).join('');
}
function tableHtml(table,terms) {
  const rows=[...table.querySelectorAll('tr')].filter(row=>row.closest('table')===table);
  if(!rows.length)return '';
  const header=rows[0];
  const hasHeader=[...header.children].some(c=>c.nodeName==='TH') || /项目|指标|名称|年度|20\d{2}年/.test(textOf(header));
  const rowHtml=(row,isHeader)=>{
    const cells=[...row.children].filter(c=>['TD','TH'].includes(c.nodeName));
    const html=cells.map((cell,index)=>{
      const text=textOf(cell).trim();
      const tag=isHeader || cell.nodeName==='TH' ? 'th':'td';
      const numeric=!!text && /^[+\-−]?[\d,，.\s%％()（）]+$/.test(text);
      const content=highlightEvidenceText(text,terms);
      const scope=tag==='th' ? ' scope="'+(isHeader?'col':'row')+'"':'';
      return '<'+tag+scope+spans(cell)+' class="'+(numeric?'numeric':'')+'">'+content.replace(/\n/g,'<br>')+'</'+tag+'>';
    }).join('');
    return '<tr'+(html.includes('class="evidence-highlight"')?' class="quoted-row"':'')+'>'+html+'</tr>';
  };
  return '<div class="evidence-table-scroll" role="region" aria-label="来源表格，可横向滚动" tabindex="0"><table class="evidence-table"><caption class="sr-only">来源资料提取表格</caption>'+ (hasHeader?'<thead>'+rowHtml(header,true)+'</thead>':'')+'<tbody>'+rows.slice(hasHeader?1:0).map(row=>rowHtml(row,false)).join('')+'</tbody></table></div>';
}
function markdownTable(text) {
  const lines=text.trim().split(/\r?\n/).filter(line=>line.trim());
  if(lines.length<2 || !/^\s*\|?\s*:?-{3,}/.test(lines[1]))return null;
  const cells=line=>line.trim().replace(/^\|/,'').replace(/\|$/,'').split('|').map(t=>t.trim());
  if(!lines[0].includes('|') || lines.some((line,i)=>i!==1&&!line.includes('|')))return null;
  const width=cells(lines[0]).length;
  if(lines.some((line,i)=>i!==1&&cells(line).length!==width))return null;
  return '<table>'+lines.filter((_,i)=>i!==1).map((line,i)=>'<tr>'+cells(line).map(value=>'<'+(i?'td':'th')+'>'+escape(value)+'</'+(i?'td':'th')+'>').join('')+'</tr>').join('')+'</table>';
}
export function renderEvidenceContent(content, quote = '') {
  const source=String(content ?? '');
  if(!source.trim())return '<p class="no-data">来源未提供可展示的内容。</p>';
  const markdown=markdownTable(source);
  // All HTML is parsed in an inert template. Only freshly generated table,
  // paragraph, list and inline markup is returned to the application.
  const root=fragment(markdown || source);
  const terms=quoteTerms(quote);
  function render(node) {
    if(node.nodeType===3)return highlightEvidenceText(node.nodeValue || '',terms);
    const tag=node.nodeName;
    if(blocked.has(tag))return '';
    if(tag==='TABLE')return tableHtml(node,terms);
    if(tag==='BR')return '<br>';
    const content=[...node.childNodes].map(render).join('');
    const mapped=({P:'p',DIV:'section',SECTION:'section',ARTICLE:'section',H1:'h4',H2:'h4',H3:'h4',H4:'h4',UL:'ul',OL:'ol',LI:'li',STRONG:'strong',B:'strong',EM:'em',I:'em'})[tag];
    return mapped?'<'+mapped+'>'+content+'</'+mapped+'>':content;
  }
  const html=[...root.childNodes].map(render).join('');
  return '<div class="evidence-rich-content">'+html+'</div>';
}
export function plainEvidenceText(content) {
  const root=fragment(String(content || ''));
  for(const table of [...root.querySelectorAll('table')]){
    const text=[...table.querySelectorAll('tr')].map(row=>[...row.children].filter(c=>['TD','TH'].includes(c.nodeName)).map(c=>textOf(c).trim()).join('\t')).join('\n');
    table.replaceWith(document.createTextNode('\n'+text+'\n'));
  }
  return textOf(root).trim();
}
export function evidencePdfPath(evidence) {
  const source=String(evidence.source_url || '');
  const path=source.split('#')[0];
  if(!/\.pdf$/i.test(evidence.source || '') || !/^\/v1\/documents\/[\w-]+\/original$/.test(path))return '';
  const fragmentPage=new URLSearchParams(source.split('#')[1] || '').get('page');
  const page=Number(evidence.page || fragmentPage || 1);
  return path+'#page='+(Number.isInteger(page)&&page>0?page:1)+'&view=FitH';
}

export function evidencePreviewPath(evidence) {
  const pdf=evidencePdfPath(evidence);
  if(!pdf)return '';
  const [path,hash]=pdf.split('#');
  const page=new URLSearchParams(hash).get('page');
  const terms=quoteTerms(evidence.quote).slice(0,24).join('\n').slice(0,2000);
  return path.replace(/\/original$/, '/pages/'+page+'.png')+(terms?'?highlight='+encodeURIComponent(terms):'');
}
