from enum import Enum
class Role(str, Enum):
    admin = 'admin'
    analyst = 'analyst'
    viewer = 'viewer'
class JobStatus(str, Enum):
    queued = 'queued'
    running = 'running'
    waiting = 'waiting'
    completed = 'completed'
    failed = 'failed'

class StorageState(str, Enum):
    online = 'online'
    archiving = 'archiving'
    cold = 'cold'
    restoring = 'restoring'

class ColdState(str, Enum):
    queued = 'queued'
    archiving = 'archiving'
    sealed = 'sealed'
    restore_queued = 'restore_queued'
    restoring = 'restoring'
    restored = 'restored'
    failed = 'failed'
