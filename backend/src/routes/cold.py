from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.models import ColdArchive, Dataset
from src.middlewares.auth import current_user, admin_only
from src.services import cold
from src.services.audit import record
router=APIRouter()

def _dataset(db,id):
    d=db.get(Dataset,id)
    if not d:raise HTTPException(404,'数据批次不存在')
    return d

@router.get('/datasets/{id}/cold')
def status(id:int,db=Depends(get_db),u=Depends(current_user)):
    d=_dataset(db,id)
    a=cold.archive_of(db,d.id)
    if not a:return {'dataset_id':d.id,'dataset_name':d.name,'storage_state':d.storage_state,'state':'online','row_count':d.row_count,'location':'','blocked_reason':'','waiting_jobs':0}
    return cold.cold_dict(db,a,d)

@router.get('/cold-archives')
def listing(db=Depends(get_db),u=Depends(current_user)):
    rows=[]
    for a in db.scalars(select(ColdArchive).order_by(ColdArchive.id.desc())):
        rows.append(cold.cold_dict(db,a))
    return rows

@router.post('/datasets/{id}/cold/archive',status_code=202)
def archive(id:int,db=Depends(get_db),u=Depends(admin_only)):
    d=_dataset(db,id)
    a=cold.request_archive(db,d)
    record(db,u.email,'cold.archive.request',{'dataset':d.id,'archive':a.id,'state':a.state})
    db.commit(); return cold.cold_dict(db,a,d)

@router.post('/datasets/{id}/cold/restore',status_code=202)
def restore(id:int,db=Depends(get_db),u=Depends(admin_only)):
    d=_dataset(db,id)
    a,reason=cold.request_restore(db,d)
    if not a:raise HTTPException(409,reason)
    record(db,u.email,'cold.restore.request',{'dataset':d.id,'archive':a.id,'state':a.state})
    db.commit(); return cold.cold_dict(db,a,d)

@router.post('/datasets/{id}/cold/retry',status_code=202)
def retry(id:int,db=Depends(get_db),u=Depends(admin_only)):
    d=_dataset(db,id)
    a=cold.request_retry(db,d)
    record(db,u.email,'cold.retry',{'dataset':d.id,'archive':a.id,'operation':a.operation,'state':a.state})
    db.commit(); return cold.cold_dict(db,a,d)
