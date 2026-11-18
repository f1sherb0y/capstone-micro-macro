"""Retain explicitly supplied paired callbacks without invoking or inspecting state."""
from copy import deepcopy
from contextlib import contextmanager
from functools import partial
from types import MappingProxyType

from src.actions.implementation import callable_implementation
from src.coordination.tasks import TaskConflict, task_digest


def _callback_implementation(callback):
    implementation = callable_implementation(callback)
    # Standard @contextmanager/@wraps factories otherwise fingerprint only
    # their shared decorator wrapper, hiding the original generator/body code.
    target, seen, wrapped = callback, set(), []
    while True:
        if id(target) in seen:
            raise TaskConflict('Paired callback declares a cyclic wrapper chain')
        seen.add(id(target))
        if isinstance(target, partial):
            target = target.func
            continue
        target = getattr(target, '__wrapped__', None)
        if target is None:
            break
        if not callable(target):
            raise TaskConflict('Paired callback wrapper must declare an actual callable implementation')
        wrapped.append(callable_implementation(target))
    if wrapped:
        implementation['wrapped_implementations'] = wrapped
    return implementation


class PairedCallbackSet:
    """Pin callback objects and source/runtime code for one original operation.

    Captured settings/instance/closure/partial arguments still need explicit
    application versions and the original source/authorization gates.
    """
    def __init__(self, **callbacks):
        if any(callback is not None and not callable(callback) for callback in callbacks.values()):
            raise TaskConflict('Paired callback binding requires original callables or explicit absence')
        self._callbacks = MappingProxyType(dict(callbacks))
        self._evidence = {'schema_version': 'paired-callback-set.v1',
            'callbacks': self._implementations()}
        self._evidence['record_sha256'] = task_digest(self._evidence)
        self._record_sha256 = self._evidence['record_sha256']

    def _implementations(self):
        return {name: _callback_implementation(callback) if callback is not None else None
            for name, callback in self._callbacks.items()}

    def check(self, **current):
        if (current and (set(current) != set(self._callbacks)
                or any(current[name] is not callback for name, callback in self._callbacks.items()))
                or self._evidence.get('record_sha256') != self._record_sha256
                or task_digest({key: value for key, value in self._evidence.items() if key != 'record_sha256'})
                    != self._record_sha256
                or task_digest(self._implementations()) != task_digest(self._evidence['callbacks'])):
            raise TaskConflict('Paired original callback objects, presence or runtime implementation changed')

    def evidence(self):
        self.check()
        return deepcopy(self._evidence)

    def invoke(self, callback_name, *args, **kwargs):
        self.check()
        callback = self._callbacks[callback_name]
        if callback is None:
            raise TaskConflict('Paired operation cannot invoke an absent optional callback')
        try:
            return callback(*args, **kwargs)
        finally:
            self.check()

    @contextmanager
    def guard(self, callback_name, *args, **kwargs):
        """Recheck through the original context manager's enter/exit as well."""
        try:
            with self.invoke(callback_name, *args, **kwargs) as guarded:
                self.check()
                yield guarded
        finally:
            self.check()


def check_saved_paired_callbacks(record, *, required):
    """Check declared archived code evidence only; construct/invoke no callback."""
    required = set(required)
    if (not isinstance(record, dict) or set(record) != {'schema_version', 'callbacks', 'record_sha256'}
            or record.get('schema_version') != 'paired-callback-set.v1'
            or record.get('record_sha256') != task_digest({key: value for key, value in record.items() if key != 'record_sha256'})
            or not isinstance(record.get('callbacks'), dict)
            or not required <= set(record['callbacks'])):
        raise TaskConflict('Saved paired callback evidence lost its original declaration or digest')
    for name, implementation in record['callbacks'].items():
        if implementation is None:
            if name in required:
                raise TaskConflict('Saved paired callback evidence omits a required original gate')
        elif (not isinstance(implementation, dict)
                or implementation.get('schema_version') != 'action-callable-implementation.v1'):
            raise TaskConflict('Saved paired callback evidence changes its original implementation format')


def check_paired_callback_association(actual, application, names):
    """Relate exact callback implementations to the original application seal."""
    check_saved_paired_callbacks(actual, required=())
    check_saved_paired_callbacks(application, required=())
    for current, original in names.items():
        if (current not in actual['callbacks'] or original not in application['callbacks']
                or task_digest(actual['callbacks'][current]) != task_digest(application['callbacks'][original])):
            raise TaskConflict('Paired callback differs from its original application dependency')
