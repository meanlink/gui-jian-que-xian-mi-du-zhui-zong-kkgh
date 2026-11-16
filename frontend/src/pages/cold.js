import {cold,datasets,jobs} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {stateLabel} from '../constants/enums.js';
import {esc,date,notify} from '../utils/dom.js';

const BUSY=['queued','archiving','restore_queued','restoring'];
const STORAGE={online:'在线',archiving:'正在冷存',cold:'已冷存',restoring:'取回中'};
let poller=null;

function bytes(value){
 if(!Number.isFinite(Number(value))||Number(value)<=0)return '—';
 const units=['B','KB','MB','GB'];let v=Number(value),i=0;
 while(v>=1024&&i<units.length-1){v/=1024;i++;}
 return v.toFixed(i?1:0)+' '+units[i];
}
function bar(archive){
 const progress=Number(archive.progress)||0;
 return '<div class="cold-progress" title="'+progress+'%"><span style="width:'+Math.min(100,progress)+'%"></span></div><small>'+progress+'% · '+bytes(archive.bytes_done)+' / '+bytes(archive.size_bytes)+'</small>';
}
function actions(a,admin){
 if(!admin)return '<span class="cold-note">只读</span>';
 if(a.state==='failed')return '<button class="button small" data-retry="'+a.dataset_id+'">重试'+(a.operation==='restore'?'取回':'搬移')+'</button>';
 if(a.state==='sealed')return '<button class="button small" data-restore="'+a.dataset_id+'">取回</button>';
 if(a.state==='restored')return '<button class="button small" data-archive="'+a.dataset_id+'">再次转入冷存</button>';
 return '<span class="cold-note">'+(BUSY.includes(a.state)?'后台处理中':'—')+'</span>';
}
function archiveCard(a,admin){
 const stateClass=String(a.state||'');
 return '<article class="cold-card '+esc(stateClass)+'"><header><div><strong>'+esc(a.dataset_name||('批次 '+a.dataset_id))+'</strong><p>'+esc(a.source||'')+' · '+(a.row_count||0)+' 个原始点 · 内容指纹 '+esc(String(a.checksum||'').slice(0,20))+'…</p></div><span class="cold-badge '+esc(stateClass)+'">'+esc(stateLabel('cold',a.state))+'</span></header><div class="cold-meta"><span>阶段</span><strong>'+esc(a.stage||'—')+'</strong><span>位置</span><strong class="mono">'+esc(a.location||a.object_key||'尚未生成')+'</strong><span>清单</span><strong class="mono">'+esc(a.manifest_location||a.manifest_key||'—')+'</strong><span>文件指纹</span><strong class="mono">'+esc(String(a.file_checksum||'—').slice(0,24))+'</strong>'+(a.sealed_at?'<span>封存</span><strong>'+date(a.sealed_at)+'</strong>':'')+(a.restored_at?'<span>取回</span><strong>'+date(a.restored_at)+'</strong>':'')+'<span>等待试验</span><strong>'+Number(a.waiting_jobs||0)+' 个</strong></div>'+bar(a)+(a.blocked_reason?'<p class="cold-blocked">阻断原因：'+esc(a.blocked_reason)+'</p>':'')+(a.error&&a.error!==a.blocked_reason?'<p class="cold-note">最近错误：'+esc(a.error)+'</p>':'')+'<footer><small>搬移尝试 '+(a.attempts||0)+' 次 · 取回尝试 '+(a.restore_attempts||0)+' 次</small>'+actions(a,admin)+'</footer></article>';
}
export async function coldPage(){
 const [archives,batchList,allJobs]=await Promise.all([cold.archives(),datasets.list(),jobs.list()]);
 workspace.coldArchives=archives;workspace.datasets=batchList;
 const admin=session.user.role==='admin';
 const archived=new Set(archives.map(a=>a.dataset_id));
 const waiting=allJobs.filter(j=>j.status==='waiting');
 const busy=archives.some(a=>BUSY.includes(a.state));
 const rows=batchList.map(d=>{
   const a=archives.find(x=>x.dataset_id===d.id);
   let action='<span class="cold-note">—</span>';
   if(admin){
     if(!a&&d.storage_state==='online')action='<button class="button small" data-archive="'+d.id+'">转入冷存</button>';
     else if(!a)action='<span class="cold-note">状态异常</span>';
     else action=actions(a,admin);
   }
   return '<tr><td><strong>'+esc(d.name)+'</strong><small>'+esc(d.source)+'</small></td><td>'+d.rows+'</td><td><span class="cold-badge '+esc(d.storage_state)+'">'+esc(STORAGE[d.storage_state]||d.storage_state)+'</span></td><td class="mono">'+esc(String(d.checksum).slice(0,16))+'…</td><td>'+action+'</td></tr>';
 }).join('');
 return heading('06 / COLD TIER','冷存与取回','把历史批次转入独立冷存卷：保留目录、试验与简报，冷副本核齐后才释放在线原始点；新试验遇到冷存批次先等待，全部校验通过才计算。',(busy?'<span class="cold-note">后台正在搬移/取回，页面自动刷新</span> ':'')+'<button class="button" id="refresh-cold">刷新状态 ↻</button>')
 +'<section class="panel"><div class="section-title"><h2>冷存台账</h2><span>'+archives.length+' 个批次 · 独立卷 cold-store</span></div>'+(archives.length?archives.map(a=>archiveCard(a,admin)).join(''):'<div class="empty">尚无冷存批次。可在下方把历史批次转入冷存。释放后目录、试验与简报仍可查阅。</div>')+'</section>'
 +'<section class="panel"><div class="section-title"><h2>批次存储位置</h2><span>原始点 '+(admin?'由负责人发起冷存':'只读查看')+'</span></div><div class="table-wrap"><table><thead><tr><th>批次</th><th>原始点数</th><th>存储状态</th><th>内容指纹</th><th>操作</th></tr></thead><tbody>'+rows+'</tbody></table></div><p class="hint">冷存搬移期间保留在线副本；只有冷存副本从磁盘回读、点数与内容指纹全部一致后才释放在线原始点。半成品不会对外开放。</p></section>'
 +'<section class="panel"><div class="section-title"><h2>等待取回的试验</h2><span>'+waiting.length+' 个</span></div>'+(waiting.length?'<ul class="waiting-list">'+waiting.map(j=>'<li><div><strong>'+esc(j.name)+'</strong><p>'+esc(j.wait_reason||'等待冷存取回')+'</p></div><small>批次 '+j.dataset_id+' · 任务 #'+j.id+'</small></li>').join('')+'</ul>':'<div class="empty">没有等待中的试验。新试验遇到冷存批次会自动登记等待，并在校验通过后恢复计算。</div>')+'</section>';
}
export function bindCold(refresh){
 if(poller){clearTimeout(poller);poller=null;}
 document.querySelector('#refresh-cold').onclick=refresh;
 const run=async(kind,id)=>{
   try{
     await ({archive:cold.archive,restore:cold.restore,retry:cold.retry})[kind](Number(id));
     notify(kind==='archive'?'已发起冷存，后台搬移并核对副本':kind==='restore'?'已发起取回，校验通过后自动计算':'已重试，将从原进度续传');
     await refresh();
   }catch(e){notify(e.message,true);}
 };
 document.querySelectorAll('[data-archive]').forEach(b=>b.onclick=()=>run('archive',b.dataset.archive));
 document.querySelectorAll('[data-restore]').forEach(b=>b.onclick=()=>run('restore',b.dataset.restore));
 document.querySelectorAll('[data-retry]').forEach(b=>b.onclick=()=>run('retry',b.dataset.retry));
 // 仅在有进行中的搬移/取回时自动刷新
 if(workspace.coldArchives.some(a=>BUSY.includes(a.state))&&location.hash.startsWith('#/cold'))poller=setTimeout(refresh,3000);
}
