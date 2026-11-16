import {datasets} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {table} from '../components/common/table.js';
import {esc,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
import {parseCSV} from '../utils/csv.js';
export async function dataPage(){
 workspace.datasets=await datasets.list();let selected=workspace.datasets[0]?await datasets.get(workspace.datasets[0].id):null,m=workspace.meta;
 const storage={online:'在线',archiving:'正在冷存',cold:'已冷存',restoring:'取回中'};
 const offline=selected&&selected.storage_state!=='online'&&selected.storage_state!=='archiving';
 return heading('02 / DATA INTAKE','数据接入与批次追溯','保留原始业务字段、来源和内容指纹。分析任务始终绑定一个不可变数据批次；冷存批次释放在线原始点后仍保留目录、内容指纹与历史试验。')+'<div class="dataset-grid"><section class="panel"><div class="section-title"><h2>业务批次</h2><span>'+workspace.datasets.length+' 批</span></div><div class="batch-list">'+workspace.datasets.map(d=>'<button class="batch-item" data-dataset="'+d.id+'"><strong>'+esc(d.name)+'</strong><span>'+d.rows+' 条 · '+esc(d.source)+'</span><small>'+esc(storage[d.storage_state]||d.storage_state||'在线')+' · SHA256 '+esc(d.checksum.slice(0,18))+'…</small></button>').join('')+'</div><div class="section-title"><h2>接入新数据</h2></div><form id="dataset-form"><label>批次名称<input name="name" required minlength="2" placeholder="例如：11 月复测批次"></label><label>上传 CSV 或 JSON<input type="file" id="file-input" accept=".json,.csv"></label><label>记录 JSON<textarea name="records" rows="6" placeholder="粘贴 JSON 数组，或先选择上方文件" required></textarea></label><p class="hint">字段：'+m.columns.map(c=>esc(c.key)+' / '+esc(c.label)).join('，')+'。5–5,000 条记录。</p><button type="submit" class="primary" '+(session.user.role==='viewer'?'disabled':'')+'>校验并接入批次</button></form></section><section class="panel"><div class="section-title"><h2 id="preview-name">'+esc(selected?.name||'尚无批次')+'</h2><span>'+(offline?'在线原始点已转入冷存':'预览前 30 条')+'</span></div><div id="data-preview">'+(offline?'<div class="empty">该批次在线原始点已释放到冷存，当前位置：冷存卷。目录、内容指纹与历史试验仍可查阅。<a href="#/cold">前往冷存与取回 ↗</a></div>':table(m.columns,selected?.records?.slice(0,30)||[]))+'</div>'+(offline?'':'<p class="hint">批次点数 '+selected?.row_count+'。冷存后此处原始点不再在线读取。</p>')+'</section></div>';
}
export function bindData(refresh){
 let source='manual.json';
 document.querySelector('#file-input').addEventListener('change',async e=>{try{const file=e.target.files[0];if(!file)return;source=file.name;const text=await file.text(),records=file.name.endsWith('.csv')?parseCSV(text):JSON.parse(text);document.querySelector('[name=records]').value=JSON.stringify(records,null,2);}catch(error){notify(error.message,true);}});
 document.querySelectorAll('[data-dataset]').forEach(button=>button.onclick=async()=>{try{const d=await datasets.get(button.dataset.dataset),storage={online:'在线',archiving:'正在冷存',cold:'已冷存',restoring:'取回中'};document.querySelector('#preview-name').textContent=d.name;const offline=d.storage_state!=='online'&&d.storage_state!=='archiving';document.querySelector('#data-preview').innerHTML=offline?'<div class="empty">该批次在线原始点已释放到冷存，当前位置：冷存卷。目录、内容指纹与历史试验仍可查阅。<a href="#/cold">前往冷存与取回 ↗</a></div>':table(workspace.meta.columns,d.records.slice(0,30));}catch(error){notify(error.message,true);}});
 submit(document.querySelector('#dataset-form'),async f=>{await datasets.create({name:f.get('name'),source,records:JSON.parse(f.get('records'))});notify('数据已接入，可前往工作台执行分析');await refresh();});
}
