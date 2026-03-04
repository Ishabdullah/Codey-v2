"""
TaskQueue — persistent subtask list with status tracking.
"""
import json
import os
import hashlib
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional
from datetime import datetime

SESSIONS_DIR = Path.home() / '.codey_sessions'

STATUS_PENDING  = 'pending'
STATUS_RUNNING  = 'running'
STATUS_DONE     = 'done'
STATUS_FAILED   = 'failed'
STATUS_SKIPPED  = 'skipped'

@dataclass
class Task:
    id: int
    description: str
    status: str = STATUS_PENDING
    result: str = ''
    error: str = ''

class TaskQueue:
    def __init__(self, name='', project_dir=None):
        self.name = name
        self.project_dir = project_dir or os.getcwd()
        self.tasks = []
        self.created_at = datetime.now().isoformat()
        self.original_request = ''
        self._path = None

    def add(self, description):
        t = Task(id=len(self.tasks)+1, description=description)
        self.tasks.append(t)
        return t

    def current(self):
        """Return first pending or running task."""
        for t in self.tasks:
            if t.status in (STATUS_PENDING, STATUS_RUNNING):
                return t
        return None

    def mark_running(self, task_id):
        for t in self.tasks:
            if t.id == task_id:
                t.status = STATUS_RUNNING
                break
        self.save()

    def mark_done(self, task_id, result=''):
        for t in self.tasks:
            if t.id == task_id:
                t.status = STATUS_DONE
                t.result = result[:300]
                break
        self.save()

    def mark_failed(self, task_id, error=''):
        for t in self.tasks:
            if t.id == task_id:
                t.status = STATUS_FAILED
                t.error = error[:300]
                break
        self.save()

    def is_complete(self):
        return all(t.status in (STATUS_DONE, STATUS_SKIPPED) for t in self.tasks)

    def pending_count(self):
        return sum(1 for t in self.tasks if t.status == STATUS_PENDING)

    def done_count(self):
        return sum(1 for t in self.tasks if t.status == STATUS_DONE)

    def _queue_path(self):
        if self._path:
            return self._path
        SESSIONS_DIR.mkdir(exist_ok=True)
        key = hashlib.md5(self.project_dir.encode()).hexdigest()[:8]
        proj = Path(self.project_dir).name
        ts = datetime.now().strftime('%H%M%S')
        self._path = SESSIONS_DIR / f'queue_{proj}_{key}_{ts}.json'
        return self._path

    def save(self):
        path = self._queue_path()
        data = {
            'name': self.name,
            'project_dir': self.project_dir,
            'original_request': self.original_request,
            'created_at': self.created_at,
            'tasks': [asdict(t) for t in self.tasks],
        }
        path.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text())
        q = cls(name=data.get('name',''), project_dir=data.get('project_dir',''))
        q.original_request = data.get('original_request','')
        q.created_at = data.get('created_at','')
        q._path = Path(path)
        for td in data.get('tasks',[]):
            t = Task(**td)
            q.tasks.append(t)
        return q

def list_queues():
    """Return all saved queues sorted by newest first."""
    SESSIONS_DIR.mkdir(exist_ok=True)
    paths = sorted(SESSIONS_DIR.glob('queue_*.json'),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    result = []
    for p in paths:
        try:
            q = TaskQueue.load(p)
            result.append((p, q))
        except Exception:
            pass
    return result
