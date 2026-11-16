import time, json, logging
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Job, Dataset, Report
from src.services import cold
from src.services.business import analyze
from src.services.reports import deliver
from src.services.audit import record
from src.utils.serialization import checksum
logging.basicConfig(level=logging.INFO)

def _wait(db, job, dataset, reason):
    """缺件、篡改或取回未完成：保持等待并写明原因，绝不读取半成品。"""
    job.status='waiting'; job.wait_reason=reason; job.error=''
    # 若批次已转入冷存，顺带登记共用取回；已有取回/受阻状态时保持原进度。
    if not cold.has_online_records(dataset):
        _, latest = cold.request_restore(db, dataset)
        if latest: job.wait_reason = latest
    record(db,'worker','job.waiting',{'id':job.id,'reason':job.wait_reason,'dataset':dataset.id})
    db.commit()

def execute(job_id):
    with Session() as db:
        j=db.get(Job,job_id)
        if not j or j.status!='queued':return
        d=db.get(Dataset,j.dataset_id)
        if not d:
            j.status='failed'; j.error='数据批次不存在'; j.finished_at=time.time(); db.commit(); return
        if not cold.has_online_records(d):
            _,reason=cold.request_restore(db,d)
            db.commit(); _wait(db,j,d,reason); return
        if not d.records:
            db.commit(); _wait(db,j,d,'在线原始点为空（可能正在冷存清退），保持等待'); return
        j.status='running'; j.wait_reason=''; db.commit()
        try:
            # 再读一次并核对批次仍在线且指纹一致，避免清退与计算并发时读到空集。
            fresh=db.get(Dataset,j.dataset_id)
            db.refresh(fresh)
            if not fresh or not cold.has_online_records(fresh) or not fresh.records or checksum(fresh.records)!=fresh.checksum:
                j.status='waiting'; j.wait_reason='批次在计算前转入冷存或在线原始点不完整，保持等待'
                record(db,'worker','job.waiting',{'id':j.id,'reason':j.wait_reason}); db.commit(); return
            result=analyze(fresh.records,j.params)
            json.dumps(result,allow_nan=False)
            j.result=result;j.status='completed';j.finished_at=time.time()
            record(db,'worker','job.completed',{'id':j.id})
        except Exception as e:
            logging.exception('Analysis failed')
            j.status='failed';j.error=str(e)[:990];j.finished_at=time.time()
            record(db,'worker','job.failed',{'id':j.id,'error':j.error})
        db.commit()

def tick():
    released=[]
    with Session() as db:
        released=cold.process_pending(db)
    with Session() as db:
        queued=list(db.scalars(select(Job.id).where(Job.status=='queued').limit(3)))
    for job_id in queued:execute(job_id)
    with Session() as db:
        for r in db.scalars(select(Report).where(Report.enabled==True,Report.next_run<=time.time())):
            d=deliver(db,r)
            if d:record(db,'worker','report.delivered',{'id':r.id,'delivery':d.id})
        db.commit()
    for job_id in released:
        with Session() as db:
            record(db,'worker','job.resumed',{'id':job_id})

def main():
    r=Redis.from_url(REDIS_URL,socket_timeout=3)
    # This Compose stack has a single worker. A crash must not strand its jobs.
    with Session() as db:
        for j in db.scalars(select(Job).where(Job.status=='running')):
            j.status='queued';record(db,'worker','job.recovered',{'id':j.id})
        db.commit()
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item=r.blpop('analysis:queue',timeout=1)
            if item:execute(int(item[1]))
            tick()
        except Exception:
            logging.exception('Worker retry');time.sleep(2)
if __name__=='__main__':main()
