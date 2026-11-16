"""批次冷存：可续传的搬移/取回、核齐后才释放或恢复原始点。

设计要点：
- 每个批次最多一条 ColdArchive（dataset_id 唯一），重试复用同一条记录，不会新增批次。
- 搬移与取回都先写 staging 半成品并记录 bytes_done；中断后按原偏移续传。
- 冷存副本从磁盘回读校验（文件指纹、点数、内容指纹）通过后，才在一个事务内
  释放在线 records 或恢复在线 records；半成品始终不对外开放。
- 数据集行在释放/恢复事务中加行锁，避免清退与新试验并发时读到空批次。
"""
import hashlib, json, logging, os, time
from fastapi import HTTPException
from sqlalchemy import func, select
from src.config.database import Session
from src.config.settings import COLD_STORE_DIR
from src.constants.enums import ColdState, JobStatus, StorageState
from src.models import ColdArchive, Dataset, Job
from src.services.audit import record
from src.utils.serialization import checksum

CHUNK = 64 * 1024
STAGING = '.staging'
MAX_AUTO_ATTEMPTS = 5
ONLINE_STATES = (StorageState.online.value, StorageState.archiving.value)


def has_online_records(dataset):
    """在线原始点是否可直接读取。搬移中的批次仍保留完整在线副本。"""
    return dataset.storage_state in ONLINE_STATES


def archive_of(db, dataset_id):
    return db.scalar(select(ColdArchive).where(ColdArchive.dataset_id == dataset_id))


def _partial_path(dataset_id, kind):
    return os.path.join(COLD_STORE_DIR, STAGING, f'{dataset_id}.{kind}.partial')


def _dataset_dir(dataset_id):
    return os.path.join(COLD_STORE_DIR, str(dataset_id))


def _object_key(dataset_id):
    return f'{dataset_id}/data.json'


def _manifest_key(dataset_id):
    return f'{dataset_id}/manifest.json'


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')


def _hash_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(CHUNK), b''):
            digest.update(block)
    return digest.hexdigest()


def _write_atomic(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + '.tmp'
    with open(temp, 'wb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def _resume_offset(path, payload):
    """只接受与源内容一致的前缀，否则从头开始，避免续传出错位副本。"""
    if not os.path.exists(path):
        return 0
    size = os.path.getsize(path)
    if size <= 0 or size > len(payload):
        return 0
    with open(path, 'rb') as handle:
        prefix = handle.read(size)
    return size if payload.startswith(prefix) else 0


def _lock_dataset(db, dataset_id):
    return db.scalars(select(Dataset).where(Dataset.id == dataset_id).with_for_update()).first()


def _block(db, archive, reason, *, restore, dataset=None):
    """受阻即保持等待：不释放、不恢复、清除半成品，并写清原因。"""
    archive.state = ColdState.failed.value
    archive.stage = '取回受阻' if restore else '搬移受阻'
    archive.blocked_reason = reason
    archive.error = reason
    archive.updated_at = time.time()
    if dataset is not None:
        dataset.storage_state = StorageState.cold.value if restore else StorageState.online.value
    if restore:
        try:
            os.remove(_partial_path(archive.dataset_id, 'restore'))
        except FileNotFoundError:
            pass
        archive.bytes_done = 0
        archive.progress = 0
        waiting = list(db.scalars(select(Job).where(Job.dataset_id == archive.dataset_id, Job.status == JobStatus.waiting.value)))
        for job in waiting:
            job.wait_reason = f'冷存取回受阻：{reason}；保持等待，可在冷存页重试取回。'
    record(db, 'worker', 'cold.restore.failed' if restore else 'cold.archive.failed', {'dataset': archive.dataset_id, 'reason': reason})


# ---------------------------------------------------------------- 发起端

def request_archive(db, dataset):
    existing = archive_of(db, dataset.id)
    if existing:
        if existing.state == ColdState.failed.value and existing.operation == 'archive' and has_online_records(dataset):
            existing.state = ColdState.archiving.value
            existing.error = ''
            existing.blocked_reason = ''
            existing.stage = '等待续传'
            existing.attempts = 0
            existing.updated_at = time.time()
            dataset.storage_state = StorageState.archiving.value
            return existing
        if existing.state == ColdState.restored.value and has_online_records(dataset):
            # 取回后再次冷存：复用同一条台账，不新增批次记录
            existing.state = ColdState.archiving.value
            existing.operation = 'archive'
            existing.error = ''
            existing.blocked_reason = ''
            existing.stage = '等待搬移'
            existing.attempts = 0
            existing.restore_attempts = 0
            existing.progress = 0
            existing.bytes_done = 0
            existing.updated_at = time.time()
            dataset.storage_state = StorageState.archiving.value
            return existing
        if existing.state in (ColdState.queued.value, ColdState.archiving.value):
            return existing
        raise HTTPException(409, '该批次已有冷存副本或取回进行中，不能重复搬移；如需读回请重试取回')
    if not has_online_records(dataset):
        raise HTTPException(409, '该批次原始点已不在线，不能发起冷存')
    if not dataset.records:
        raise HTTPException(409, '该批次没有在线原始点，不能冷存')
    if checksum(dataset.records) != dataset.checksum:
        raise HTTPException(409, '在线原始点内容指纹已不一致，已拒绝冷存')
    archive = ColdArchive(
        dataset_id=dataset.id, state=ColdState.queued.value, operation='archive',
        content_checksum=dataset.checksum, row_count=len(dataset.records),
        stage='等待搬移', created_at=time.time(), updated_at=time.time(),
    )
    db.add(archive)
    dataset.storage_state = StorageState.archiving.value
    db.flush()
    return archive


def request_restore(db, dataset):
    """幂等：多个试验共用同一次取回，已在取回/排队时不重置进度。"""
    if has_online_records(dataset) and dataset.records:
        raise HTTPException(409, '该批次原始点已在线，无需取回')
    archive = archive_of(db, dataset.id)
    if not archive:
        return None, '该批次已冷存但缺少冷存台账，无法自动取回'
    if archive.state in (ColdState.queued.value, ColdState.archiving.value):
        return archive, '该批次正在搬入冷存，暂不读取原始点'
    if archive.state in (ColdState.restore_queued.value, ColdState.restoring.value):
        return archive, '数据批次正在从冷存取回，等待全部校验通过后计算'
    if archive.state == ColdState.failed.value:
        return archive, f'冷存取回受阻：{archive.blocked_reason or archive.error or "副本校验未通过"}；保持等待，可重试取回'
    if archive.state == ColdState.sealed.value:
        archive.state = ColdState.restore_queued.value
        archive.operation = 'restore'
        archive.stage = '等待取回'
        archive.error = ''
        archive.blocked_reason = ''
        archive.updated_at = time.time()
        dataset.storage_state = StorageState.restoring.value
        return archive, '数据批次位于冷存，已发起取回，等待校验通过后计算'
    # restored 但数据集不在线：视为台账不一致，重新排队取回
    archive.state = ColdState.restore_queued.value
    archive.operation = 'restore'
    archive.stage = '等待取回'
    archive.updated_at = time.time()
    dataset.storage_state = StorageState.restoring.value
    return archive, '数据批次位于冷存，已发起取回，等待校验通过后计算'


def request_retry(db, dataset):
    archive = archive_of(db, dataset.id)
    if not archive:
        raise HTTPException(404, '该批次没有冷存记录')
    if archive.state != ColdState.failed.value:
        raise HTTPException(409, '当前冷存状态无需重试')
    archive.error = ''
    archive.blocked_reason = ''
    archive.stage = '等待重试'
    archive.updated_at = time.time()
    # 保留 bytes_done，续传而不重复搬移
    if archive.operation == 'archive':
        archive.state = ColdState.archiving.value
        archive.attempts = 0
        dataset.storage_state = StorageState.archiving.value
    else:
        archive.state = ColdState.restore_queued.value
        archive.restore_attempts = 0
        dataset.storage_state = StorageState.restoring.value
        archive.stage = '等待继续取回' if archive.bytes_done else '等待取回'
    return archive


# ---------------------------------------------------------------- 搬移

def _existing_sealed(dataset_id, expected_checksum, expected_rows):
    data_path = os.path.join(_dataset_dir(dataset_id), 'data.json')
    manifest_path = os.path.join(_dataset_dir(dataset_id), 'manifest.json')
    if not os.path.exists(data_path) or not os.path.exists(manifest_path):
        return None
    try:
        with open(manifest_path, 'rb') as handle:
            manifest = json.loads(handle.read())
        if manifest.get('content_checksum') != expected_checksum or manifest.get('rows') != expected_rows:
            return None
        if _hash_file(data_path) != manifest.get('file_checksum'):
            return None
        with open(data_path, 'rb') as handle:
            rows = json.loads(handle.read())
        if len(rows) != expected_rows or checksum(rows) != expected_checksum:
            return None
        return manifest
    except (OSError, ValueError):
        return None


def _copy_with_progress(source, partial, archive_id, total, kind):
    offset = _resume_offset(partial, source)
    os.makedirs(os.path.dirname(partial), exist_ok=True)
    last_percent = -1
    with open(partial, 'wb' if offset == 0 else 'r+b') as handle:
        handle.seek(offset)
        handle.truncate()
        position = offset
        while position < total:
            piece = source[position:position + CHUNK]
            handle.write(piece)
            handle.flush()
            os.fsync(handle.fileno())
            position += len(piece)
            percent = int(position / total * 100) if total else 100
            if percent != last_percent:
                with Session() as pdb:
                    row = pdb.get(ColdArchive, archive_id)
                    if row:
                        row.bytes_done = position
                        row.progress = percent
                        row.updated_at = time.time()
                        pdb.commit()
                last_percent = percent
    return offset


def _run_archive(dataset_id):
    with Session() as db:
        archive = archive_of(db, dataset_id)
        dataset = db.get(Dataset, dataset_id)
        if not archive or not dataset or archive.state not in (ColdState.queued.value, ColdState.archiving.value):
            return
        if dataset.storage_state != StorageState.archiving.value:
            _block(db, archive, '批次状态与冷存台账不一致，停止搬移', restore=False, dataset=dataset)
            db.commit()
            return
        if checksum(dataset.records) != dataset.checksum:
            _block(db, archive, '在线原始点内容指纹不一致，停止搬移', restore=False, dataset=dataset)
            db.commit()
            return
        rows = list(dataset.records)
        expected_checksum = dataset.checksum
        expected_rows = len(rows)
        payload = _canonical(rows)
        archive.state = ColdState.archiving.value
        archive.operation = 'archive'
        archive.size_bytes = len(payload)
        archive.row_count = expected_rows
        archive.content_checksum = expected_checksum
        archive.attempts += 1
        archive.stage = '复制冷存副本'
        archive.error = ''
        archive.blocked_reason = ''
        archive.updated_at = time.time()
        db.commit()
        archive_id = archive.id
        total = len(payload)

    try:
        manifest = _existing_sealed(dataset_id, expected_checksum, expected_rows)
        if manifest:
            file_checksum = manifest['file_checksum']
            total = manifest['size_bytes']
        else:
            partial = _partial_path(dataset_id, 'archive')
            _copy_with_progress(payload, partial, archive_id, total, 'archive')
            if os.path.getsize(partial) != total:
                raise ValueError('冷存副本长度与预期不符')
            file_checksum = _hash_file(partial)
            with open(partial, 'rb') as handle:
                sealed_rows = json.loads(handle.read())
            if len(sealed_rows) != expected_rows or checksum(sealed_rows) != expected_checksum:
                raise ValueError('冷存副本点数或内容指纹与在线批次不一致')
            final_data = os.path.join(_dataset_dir(dataset_id), 'data.json')
            os.makedirs(os.path.dirname(final_data), exist_ok=True)
            os.replace(partial, final_data)
            manifest_bytes = _canonical({
                'version': 1, 'dataset_id': dataset_id, 'rows': expected_rows,
                'content_checksum': expected_checksum, 'file_checksum': file_checksum,
                'size_bytes': total, 'sealed_at': time.time(),
            })
            _write_atomic(os.path.join(_dataset_dir(dataset_id), 'manifest.json'), manifest_bytes)
            # 封存后从磁盘回读，核齐才允许释放在线原始点
            if _hash_file(final_data) != file_checksum:
                raise ValueError('冷存副本回读文件指纹不符')
            with open(final_data, 'rb') as handle:
                if checksum(json.loads(handle.read())) != expected_checksum:
                    raise ValueError('冷存副本回读内容指纹不符')
    except Exception as exc:
        logging.exception('Cold archive interrupted')
        with Session() as db:
            archive = db.get(ColdArchive, archive_id)
            if archive and archive.state in (ColdState.queued.value, ColdState.archiving.value):
                archive.error = str(exc)[:590]
                archive.stage = '搬移中断，可续传'
                archive.blocked_reason = '冷存搬移中断，保留在线原始点并等待续传'
                archive.updated_at = time.time()
                if archive.attempts >= MAX_AUTO_ATTEMPTS:
                    archive.state = ColdState.failed.value
                    archive.blocked_reason = '冷存搬移多次中断，已暂停自动重试'
                    dataset = db.get(Dataset, dataset_id)
                    if dataset:
                        dataset.storage_state = StorageState.online.value
                db.commit()
        return

    with Session() as db:
        archive = db.get(ColdArchive, archive_id)
        dataset = _lock_dataset(db, dataset_id)
        if not archive or not dataset or archive.state not in (ColdState.queued.value, ColdState.archiving.value):
            return
        if dataset.storage_state != StorageState.archiving.value or len(dataset.records) != expected_rows \
                or checksum(dataset.records) != expected_checksum:
            _block(db, archive, '搬移期间在线原始点发生变化，未释放原始点', restore=False, dataset=dataset)
            db.commit()
            return
        archive.object_key = _object_key(dataset_id)
        archive.manifest_key = _manifest_key(dataset_id)
        archive.file_checksum = file_checksum
        archive.size_bytes = total
        archive.bytes_done = total
        archive.progress = 100
        archive.state = ColdState.sealed.value
        archive.stage = '冷存副本已核齐，在线原始点已释放'
        archive.blocked_reason = ''
        archive.error = ''
        archive.sealed_at = archive.released_at = time.time()
        archive.updated_at = archive.sealed_at
        dataset.records = []
        dataset.storage_state = StorageState.cold.value
        record(db, 'worker', 'cold.sealed', {'dataset': dataset_id, 'rows': expected_rows, 'checksum': expected_checksum})
        db.commit()


# ---------------------------------------------------------------- 取回

def _read_manifest(dataset_id, dataset):
    data_path = os.path.join(_dataset_dir(dataset_id), 'data.json')
    manifest_path = os.path.join(_dataset_dir(dataset_id), 'manifest.json')
    missing = [name for name, path in (('data.json', data_path), ('manifest.json', manifest_path)) if not os.path.exists(path)]
    if missing:
        return None, None, f'冷存副本缺失（{"、".join(missing)}），保持等待'
    try:
        with open(manifest_path, 'rb') as handle:
            manifest = json.loads(handle.read())
    except (OSError, ValueError):
        return None, None, '冷存清单损坏，无法确认副本完整性'
    if manifest.get('dataset_id') != dataset_id:
        return None, None, '冷存清单与批次不匹配'
    if manifest.get('content_checksum') != dataset.checksum or manifest.get('rows') != (dataset.row_count or 0):
        return None, None, '冷存清单点数或内容指纹与原始批次不一致'
    size = os.path.getsize(data_path)
    if size != manifest.get('size_bytes') or _hash_file(data_path) != manifest.get('file_checksum'):
        return None, None, '冷存副本文件指纹不符，可能损坏或被篡改'
    return data_path, manifest, ''


def _run_restore(dataset_id):
    with Session() as db:
        archive = archive_of(db, dataset_id)
        dataset = db.get(Dataset, dataset_id)
        if not archive or not dataset or archive.state not in (ColdState.restore_queued.value, ColdState.restoring.value):
            return []
        data_path, manifest, problem = _read_manifest(dataset_id, dataset)
        if problem:
            _block(db, archive, problem, restore=True, dataset=dataset)
            db.commit()
            return []
        archive.state = ColdState.restoring.value
        archive.operation = 'restore'
        archive.restore_attempts += 1
        archive.stage = '下载冷存副本'
        archive.size_bytes = manifest['size_bytes']
        archive.progress = 0
        archive.bytes_done = 0
        archive.content_checksum = manifest['content_checksum']
        archive.row_count = manifest['rows']
        archive.updated_at = time.time()
        db.commit()
        archive_id = archive.id
        total = manifest['size_bytes']
        expected_checksum = manifest['content_checksum']
        expected_rows = manifest['rows']

    try:
        with open(data_path, 'rb') as handle:
            source = handle.read()
        if len(source) != total:
            raise ValueError('冷存副本长度与清单不符')
        partial = _partial_path(dataset_id, 'restore')
        _copy_with_progress(source, partial, archive_id, total, 'restore')
        if os.path.getsize(partial) != total:
            raise ValueError('取回副本长度不完整')
        with open(partial, 'rb') as handle:
            rows = json.loads(handle.read())
        if len(rows) != expected_rows or checksum(rows) != expected_checksum:
            raise ValueError('取回点数或内容指纹与原始批次不一致')
        if _hash_file(partial) != manifest['file_checksum']:
            raise ValueError('取回副本文件指纹不符')
    except Exception as exc:
        logging.exception('Cold restore interrupted')
        with Session() as db:
            archive = db.get(ColdArchive, archive_id)
            if archive and archive.state == ColdState.restoring.value:
                reason = str(exc)[:300]
                interrupted = not isinstance(exc, ValueError)
                archive.state = ColdState.failed.value
                archive.stage = '取回中断，可续传' if interrupted else '取回受阻'
                archive.error = reason
                archive.blocked_reason = ('取回中断，保留已下载进度，保持等待' if interrupted else '取回内容校验未通过，保持等待')
                partial = _partial_path(dataset_id, 'restore')
                if os.path.exists(partial) and archive.size_bytes:
                    archive.bytes_done = min(os.path.getsize(partial), archive.size_bytes)
                    archive.progress = int(archive.bytes_done / archive.size_bytes * 100)
                elif not interrupted:
                    archive.bytes_done = 0
                    archive.progress = 0
                if not interrupted:
                    # 校验失败说明副本内容不可信，丢弃半成品，重试时重新下载
                    try:
                        os.remove(partial)
                    except FileNotFoundError:
                        pass
                dataset = db.get(Dataset, dataset_id)
                if dataset:
                    dataset.storage_state = StorageState.cold.value
                for job in db.scalars(select(Job).where(Job.dataset_id == dataset_id, Job.status == JobStatus.waiting.value)):
                    job.wait_reason = f'冷存取回受阻：{reason}；保持等待，可在冷存页重试取回。'
                record(db, 'worker', 'cold.restore.failed', {'dataset': dataset_id, 'reason': reason})
                db.commit()
        return []

    released = []
    with Session() as db:
        archive = db.get(ColdArchive, archive_id)
        dataset = _lock_dataset(db, dataset_id)
        if not archive or not dataset or archive.state != ColdState.restoring.value:
            return []
        dataset.records = rows
        dataset.storage_state = StorageState.online.value
        archive.state = ColdState.restored.value
        archive.progress = 100
        archive.bytes_done = total
        archive.stage = '已取回并校验通过，在线可计算'
        archive.blocked_reason = ''
        archive.error = ''
        archive.restored_at = time.time()
        archive.updated_at = archive.restored_at
        for job in db.scalars(select(Job).where(Job.dataset_id == dataset_id, Job.status == JobStatus.waiting.value)):
            job.status = JobStatus.queued.value
            job.wait_reason = ''
            released.append(job.id)
        record(db, 'worker', 'cold.restored', {'dataset': dataset_id, 'rows': expected_rows, 'jobs': released})
        db.commit()
    try:
        os.remove(_partial_path(dataset_id, 'restore'))
    except FileNotFoundError:
        pass
    return released


# ---------------------------------------------------------------- worker 入口

def process_pending(db):
    """按状态续传所有冷存搬移/取回；返回可取回后恢复排队的任务号。"""
    pending = list(db.scalars(select(ColdArchive.id).where(ColdArchive.state.in_([
        ColdState.queued.value, ColdState.archiving.value,
        ColdState.restore_queued.value, ColdState.restoring.value,
    ]))).all())
    released = []
    for archive_id in pending:
        archive = db.get(ColdArchive, archive_id)
        if not archive:
            continue
        if archive.state in (ColdState.queued.value, ColdState.archiving.value):
            _run_archive(archive.dataset_id)
        else:
            released.extend(_run_restore(archive.dataset_id))
    return released


def cold_dict(db, archive, dataset=None):
    dataset = dataset or db.get(Dataset, archive.dataset_id)
    waiting = db.scalar(select(func.count()).select_from(Job).where(
        Job.dataset_id == archive.dataset_id, Job.status == JobStatus.waiting.value))
    location = os.path.join(COLD_STORE_DIR, archive.object_key) if archive.object_key else ''
    manifest_location = os.path.join(COLD_STORE_DIR, archive.manifest_key) if archive.manifest_key else ''
    return {
        'dataset_id': archive.dataset_id,
        'dataset_name': dataset.name if dataset else '',
        'source': dataset.source if dataset else '',
        'storage_state': dataset.storage_state if dataset else '',
        'state': archive.state,
        'operation': archive.operation,
        'row_count': archive.row_count,
        'checksum': archive.content_checksum,
        'file_checksum': archive.file_checksum,
        'size_bytes': archive.size_bytes,
        'bytes_done': archive.bytes_done,
        'progress': 100 if archive.state in (ColdState.sealed.value, ColdState.restored.value) else archive.progress,
        'stage': archive.stage,
        'object_key': archive.object_key,
        'manifest_key': archive.manifest_key,
        'location': location,
        'manifest_location': manifest_location,
        'attempts': archive.attempts,
        'restore_attempts': archive.restore_attempts,
        'blocked_reason': archive.blocked_reason,
        'error': archive.error,
        'waiting_jobs': int(waiting or 0),
        'sealed_at': archive.sealed_at,
        'released_at': archive.released_at,
        'restored_at': archive.restored_at,
        'created_at': archive.created_at,
        'updated_at': archive.updated_at,
    }
