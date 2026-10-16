import {parseHTML} from 'linkedom';
import test from 'node:test';
import assert from 'node:assert/strict';
import {adaptReview} from '../frontend/src/adapter.js';
import {filterFindings,renderWorkspace,renderDashboard,renderShell,renderNewReview,renderExport} from '../frontend/src/ui.js';
import {data,renderRules,renderRuntime} from '../frontend/src/workbench.js';

globalThis.document=parseHTML('<html><body></body></html>').document;
Object.defineProperty(globalThis,'localStorage',{value:{getItem:()=>''},configurable:true});
const raw={review_id:'r1',report_id:'report1',report_name:'验收报告',status:'HUMAN_REVIEW_REQUIRED',state:{original_input:'收入为120万元。净利润10万元。',fact_groups:[{parent:{parent_id:'p1'},children:[{fact_id:'f1',fact:'收入为120万元。',source_start:0,source_end:10},{fact_id:'f2',fact:'净利润10万元。',source_start:10,source_end:18}]}],completed_results:[{fact_id:'f2',fact:'净利润10万元。',status:'SUPPORTED',reason:'已核验',risk_decision:{risk_level:'low'},evidence:[]}],human_task:{fact_id:'f1',status:'PENDING',task_version:1},current_fact:{fact_id:'f1',fact:'收入为120万元。'},verification_result:{status:'INSUFFICIENT_EVIDENCE',reason:'唯一判定理由',confidence:'low'},risk_decision:{risk_level:'critical'},current_evidence:[{evidence_id:'e1',content:'唯一来源正文<script>alert(1)</script>',source:'年报',score:null},{evidence_id:'e1',content:'唯一来源正文<script>alert(1)</script>',source:'年报',score:null}],current_assessments:[{evidence_id:'e1',relation:'CONTRADICTS',rationale:'金额不同'}]}};
const review=adaptReview(raw),state={typeFilter:'',riskFilter:'',pendingOnly:false,selectedEvidenceId:'',compareMode:false};
test('high-risk filter includes critical findings',()=>assert.equal(filterFindings(review,{...state,riskFilter:'high'})[0].id,'f1'));
test('pending filter uses backend human task',()=>assert.deepEqual(filterFindings(review,{...state,pendingOnly:true}).map(f=>f.id),['f1']));
test('no match does not fall back to an excluded finding',()=>{const html=renderWorkspace(review,'f1',{...state,typeFilter:'missing'});assert.match(html,/没有匹配的复核项/);assert.doesNotMatch(html,/id="human-comment"/);});
test('explicit selection cannot bypass current risk filter',()=>{const html=renderWorkspace(review,'f1',{...state,riskFilter:'low'});assert.match(html,/已核验/);assert.doesNotMatch(html,/唯一判定理由/);});
test('decision rationale and evidence each have one display owner',()=>{const html=renderWorkspace(review,'f1',state);assert.equal(html.split('唯一判定理由').length-1,1);assert.equal(html.split('唯一来源正文').length-1,1);});
test('source content is escaped',()=>{const html=renderWorkspace(review,'f1',state);assert.doesNotMatch(html,/<script>/);assert.match(html,/唯一来源正文/);assert.doesNotMatch(html,/alert\(1\)/);});
test('decision requires explicit choice and visible reason label',()=>{const html=renderWorkspace(review,'f1',state);assert.match(html,/for="human-comment"/);assert.match(html,/id="human-comment"[^>]*required/);assert.equal((html.match(/name="decision"/g)||[]).length,3);assert.doesNotMatch(html,/name="decision"[^>]*checked/);});
test('missing score is not shown as zero confidence',()=>assert.doesNotMatch(renderWorkspace(review,'f1',state),/0\.000/));
test('stable evidence identifiers deduplicate repeated source payloads',()=>assert.equal(review.findings.find(f=>f.id==='f1').evidence.length,1));
test('unsupported rule controls are not falsely interactive',()=>{data.rules={version:'v1',human_policy:[],rules:[{rule_id:'a',issue_type:'risk_omission',severity:'high',explanation:'风险提示'}]};const html=renderRules();assert.match(html,/只读/);assert.doesNotMatch(html,/type="checkbox"/);});
test('retrieval configuration is read-only',()=>{data.runtime={provider:{base_url:'http://localhost',model:'test',wire_api:'responses',stream:false,key_configured:true},retrieval_backend:'lexical'};const html=renderRuntime();assert.match(html,/当前检索配置（只读）/);assert.doesNotMatch(html,/id="retrieval-embedding"/);});
test('active navigation and keyboard skip target remain accessible',()=>{globalThis.location={pathname:'/dashboard'};const html=renderShell('/dashboard','',true);assert.match(html,/aria-current="page"/);assert.match(html,/href="#main-content"/);});
test('new review accepts documents supported by the real backend',()=>{const html=renderNewReview({reportName:'',reportText:'',sourceFiles:[],reportType:'AI 生成报告'});assert.match(html,/\.pdf,\.docx,\.txt,\.md/);});

test('saved human rationale is displayed only once',()=>{const r=structuredClone(review);const f=r.findings.find(f=>f.id==='f1');f.humanTask=null;f.humanDecision={comment:f.reason,decided_by:'测试'};assert.equal(renderWorkspace(r,'f1',state).split('唯一判定理由').length-1,1);});

test('missing evidence requirement IDs become business descriptions',()=>{const r=structuredClone(raw);r.state.missing_needs=['N-F1'];r.state.evidence_requirements=[{need_id:'N-F1',description:'核对2024年营业收入的原始年报'}];const f=adaptReview(r).findings.find(f=>f.id==='f1');assert.deepEqual(f.missingNeeds,['核对2024年营业收入的原始年报']);assert.deepEqual(f.missingNeedIds,['N-F1']);});

test('partial exports count the displayed verdicts instead of absent final summaries',()=>{const html=renderExport(review);assert.match(html,/证据支持 <b>1<\/b>/);assert.match(html,/证据不足 <b>1<\/b>/);});

test('cancelled tasks never expose an actionable human decision',()=>{const r=structuredClone(raw);r.status='CANCELLED';const normalized=adaptReview(r);assert.equal(normalized.pendingTask,null);assert.doesNotMatch(renderWorkspace(normalized,'f1',state),/id="human-comment"/);});

test('web evidence opens a saved snapshot in the same pane with escaped highlight query',()=>{
  const r=structuredClone(raw);r.temporal_policy={as_of:'2026-10-16'};
  r.state.current_evidence=[{evidence_id:'e1',source:'公开披露',source_type:'web',snapshot_url:'/v1/documents/d1/view#P0001',content:'Revenue was $76.4 billion.',temporal:{published_at:'2025-07-30',data_period:'FY2025Q4'}}];
  r.state.current_assessments=[{evidence_id:'e1',quote:'Revenue was $76.4 billion.',relation:'SUPPORTS'}];
  r.state.verification_result.temporal_checks=[{evidence_id:'e1',eligible:false,reasons:['数据期间不匹配'],source_temporal:{data_period:'FY2024Q4'}}];
  r.state.verification_result.evidence_ids=['e1'];
  const html=renderWorkspace(adaptReview(r),'f1',{...state,webKeyword:'<script>'});
  assert.match(html,/<iframe class="web-snapshot-frame original-web-frame"/);
  assert.match(html,/sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox"/);
  assert.doesNotMatch(html,/allow-same-origin|<script>/);
  assert.match(html,/keyword=%3Cscript%3E/);
  assert.match(html,/original-view/);
  assert.match(html,/FY2025Q4/);
  assert.match(html,/2025-07-30/);
  assert.match(html,/parent=P0001/);
});

test('evidence pane defaults to an actually used supporting source',()=>{
  const r=structuredClone(raw);
  r.state.current_evidence=[{evidence_id:'irrelevant',content:'排名高但无关的候选',source:'候选'},{evidence_id:'used',content:'被实际采用的原文',source:'采用来源'}];
  r.state.current_assessments=[{evidence_id:'irrelevant',relation:'IRRELEVANT'},{evidence_id:'used',relation:'SUPPORTS'}];
  r.state.verification_result.evidence_ids=['used'];
  const html=renderWorkspace(adaptReview(r),'f1',state);
  assert.match(html,/queue-material selected[^>]*data-select-evidence="used"/);
  assert.match(html,/被实际采用的原文/);
  assert.doesNotMatch(html,/排名高但无关的候选/);
});


test('batch queue exposes every pending item and advances to the next unresolved point',()=>{
 const task=id=>({fact_id:id,status:'PENDING',task_version:1});
 const r={review_id:'batch',workflow_version:2,status:'HUMAN_REVIEW_REQUIRED',state:{completed_results:[{fact_id:'a',fact:'结论甲',status:'INSUFFICIENT_EVIDENCE',pending_review:true,human_task:task('a'),evidence:[]},{fact_id:'b',fact:'结论乙',status:'SUPPORTED',labeling_status:'failed',pending_review:true,human_task:task('b'),evidence:[]}]}};
 let adapted=adaptReview(r);assert.equal(adapted.pendingTask.fact_id,'a');assert.equal(filterFindings(adapted,{pendingOnly:true}).length,2);
 r.state.completed_results[0].pending_review=false;r.state.completed_results[0].human_task.status='RESOLVED';
 adapted=adaptReview(r);assert.equal(adapted.pendingTask.fact_id,'b');
 const html=renderWorkspace(adapted,'b',state);assert.match(html,/标签待确认/);assert.doesNotMatch(html,/未发现问题/);
 r.status='RUNNING';assert.equal(adaptReview(r).findings[1].humanTask,null);
});
