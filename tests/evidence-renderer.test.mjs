import test from 'node:test';
import assert from 'node:assert/strict';
import {parseHTML} from 'linkedom';
import {renderEvidenceContent,highlightEvidenceText,plainEvidenceText,evidencePdfPath} from '../frontend/src/evidence-renderer.js';

globalThis.document=parseHTML('<html><body></body></html>').document;
const parse=html=>{const el=document.createElement('div');el.innerHTML=html;return el;};
const table='<table><tr><td>项目</td><td>2024年</td><td>2023年</td><td>备注</td></tr><tr><td>营业收入（元）</td><td>98,660,353.71</td><td>110,048,548.32</td><td>无</td></tr><tr><td>扣除金额</td><td>953,239.14</td><td>1,384,982.64</td><td>出租收入</td></tr></table>';
const quote='<td>营业收入（元）</td><td>98,660,353.71</td>';

test('financial HTML renders actual table columns and header',()=>{
 const root=parse(renderEvidenceContent(table,quote));
 assert.equal(root.querySelectorAll('thead th').length,4);
 assert.equal(root.querySelectorAll('tbody tr').length,2);
 assert.equal(root.querySelectorAll('tbody tr')[0].children.length,4);
 assert.equal(root.querySelectorAll('tbody tr')[0].children[1].textContent,'98,660,353.71');
});
test('only the cited cells and corresponding row are highlighted',()=>{
 const root=parse(renderEvidenceContent(table,quote));
 assert.deepEqual([...root.querySelectorAll('mark')].map(e=>e.textContent),['营业收入（元）','98,660,353.71']);
 assert.equal(root.querySelectorAll('.quoted-row').length,1);
 assert.equal(root.querySelector('tbody tr:last-child mark'),null);
});
test('rowspan and colspan are preserved but hostile attributes are dropped',()=>{
 const root=parse(renderEvidenceContent('<table style="color:red"><tr><td colspan="2" onclick="alert(1)">项目</td></tr><tr><td rowspan="2">指标</td><td>10</td></tr><tr><td>20</td></tr></table>'));
 assert.equal(root.querySelector('th').getAttribute('colspan'),'2');
 assert.equal(root.querySelector('td').getAttribute('rowspan'),'2');
 assert.equal(root.querySelector('[onclick],[style]'),null);
});
test('malicious markup cannot create scripts, event handlers, links or embeds',()=>{
 const html=renderEvidenceContent('<div><script>alert(1)</script><img src="https://example.com/track" onerror="alert(2)"><svg onload="alert(3)"></svg><iframe src="https://example.com"></iframe><table><tr><td>项目</td><td><a href="javascript:alert(4)">10</a></td></tr></table></div>');
 const root=parse(html);
 assert.equal(root.querySelector('script,img,svg,iframe,a,[onload],[onerror]'),null);
 assert.doesNotMatch(html,/alert\(/);
 assert.match(html,/>10</);
});
test('unmatched quotes do not create highlights or infer values',()=>{
 const root=parse(renderEvidenceContent(table,'99,999,999.99'));
 assert.equal(root.querySelectorAll('mark').length,0);
 assert.equal(root.textContent.includes('99,999,999.99'),false);
});
test('whitespace-tolerant quote matching preserves the source number as displayed',()=>{
 const html=highlightEvidenceText('本期收入 110,048, 548.32 元',['110,048,548.32']);
 assert.match(html,/<mark[^>]*>110,048, 548.32<\/mark>/);
});
test('Chinese Unicode text surrounding a citation is preserved',()=>{
 const html=highlightEvidenceText('📄 营业收入为100万元。',['营业收入']);
 assert.equal(parse(html).textContent,'📄 营业收入为100万元。');
});
test('overlapping terms merge into a single highlight',()=>assert.equal((highlightEvidenceText('营业收入100万元',['营业收入','收入100万元']).match(/<mark/g)||[]).length,1));
test('plain paragraphs remain readable and escape entities',()=>{
 const root=parse(renderEvidenceContent('第一段：收入100万元。\n\n第二段：A & B < C。','收入100万元'));
 assert.match(root.textContent,/第一段/);assert.match(root.textContent,/A & B < C/);
 assert.equal(root.querySelector('mark').textContent,'收入100万元');
});
test('Markdown tables retain columns without guessing malformed rows',()=>{
 const root=parse(renderEvidenceContent('| 项目 | 2024年 |\n| --- | ---: |\n| 收入 | 100 |'));
 assert.equal(root.querySelectorAll('thead th').length,2);
 assert.equal(root.querySelector('tbody td:last-child').textContent,'100');
 const malformed=parse(renderEvidenceContent('项目 | 2024年\n营业收入 扣除金额 | 100 20'));
 assert.equal(malformed.querySelector('table'),null);
});
test('table clipboard content uses rows and tab-delimited cells',()=>{
 const text=plainEvidenceText(table);
 assert.match(text,/项目\t2024年\t2023年\t备注/);
 assert.match(text,/营业收入（元）\t98,660,353.71\t110,048,548.32\t无/);
 assert.doesNotMatch(text,/<td>/);
});
test('PDF preview uses the real original route and exact source page',()=>{
 assert.equal(evidencePdfPath({source:'年报.pdf',source_url:'/v1/documents/D-1/original#page=8',page:8}),'/v1/documents/D-1/original#page=8&view=FitH');
 assert.equal(evidencePdfPath({source:'来源.json',source_url:'/v1/documents/D-1/view#P3'}),'');
 assert.equal(evidencePdfPath({source:'年报.pdf',source_url:'javascript:alert(1)'}),'');
 assert.equal(evidencePdfPath({source:'年报.pdf',source_url:'https://outside.example/track.pdf'}),'');
});
test('empty content and malformed large spans degrade safely',()=>{
 assert.match(renderEvidenceContent(''),/来源未提供/);
 const root=parse(renderEvidenceContent('<table><tr><td colspan="999">项目</td></tr></table>'));
 assert.equal(root.querySelector('[colspan]'),null);
});

test('PDF image preview targets the original document and encodes literal quote terms',async()=>{
 const {evidencePreviewPath}=await import('../frontend/src/evidence-renderer.js');
 const path=evidencePreviewPath({source:'年报.pdf',source_url:'/v1/documents/D-1/original#page=8',page:8,quote});
 assert.match(path,/^\/v1\/documents\/D-1\/pages\/8\.png\?highlight=/);
 assert.match(decodeURIComponent(path),/98,660,353\.71/);
 assert.doesNotMatch(decodeURIComponent(path),/<td>/);
});
