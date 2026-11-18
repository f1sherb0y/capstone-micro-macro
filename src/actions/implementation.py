"""Fingerprint supplied executable code without calling it or inspecting secrets."""
from functools import partial
import hashlib
import json
from pathlib import Path
import struct
import sys
from types import CodeType


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def _constant(value):
    """Normalize compiler constants, including unordered folded set literals."""
    if value is None:
        return ['none']
    if value is Ellipsis:
        return ['ellipsis']
    if type(value) in (str, bool, int):
        return [type(value).__name__, value]
    if type(value) is bytes:
        return ['bytes', value.hex()]
    if type(value) is float:
        return ['float', struct.pack('>d', value).hex()]
    if type(value) is complex:
        return ['complex', struct.pack('>dd', value.real, value.imag).hex()]
    if type(value) is tuple:
        return ['tuple', [_constant(item) for item in value]]
    if type(value) is frozenset:
        return ['frozenset', sorted((_constant(item) for item in value), key=_canonical)]
    if isinstance(value, CodeType):
        return ['code', dict(name=value.co_name, qualname=getattr(value, 'co_qualname', value.co_name),
            bytecode=value.co_code.hex(), exceptions=getattr(value, 'co_exceptiontable', b'').hex(),
            constants=[_constant(item) for item in value.co_consts], names=list(value.co_names),
            varnames=list(value.co_varnames), freevars=list(value.co_freevars), cellvars=list(value.co_cellvars),
            argcount=value.co_argcount, positional_only=value.co_posonlyargcount,
            keyword_only=value.co_kwonlyargcount, locals=value.co_nlocals,
            stacksize=value.co_stacksize, flags=value.co_flags)]
    raise ValueError('Unsupported compiler constant; declare a supported executable implementation')


def callable_implementation(callback):
    """Describe actual Python code/module, including dynamically compiled code.

    Instance state, closure values and partial arguments remain the trusted
    host's explicit version/configuration responsibility. Only code digests
    are exported; no captured values, credentials or source text are returned.
    """
    if not callable(callback):
        raise ValueError('Implementation identity requires an actual callable')
    target = callback
    while isinstance(target, partial):
        target = target.func
    code = getattr(target, '__code__', None)
    if code is None:
        code = getattr(getattr(target, '__call__', None), '__code__', None)
    path = Path(code.co_filename) if code is not None else None
    return dict(schema_version='action-callable-implementation.v1',
        component=getattr(target, '__module__', type(target).__module__) + '.'
            + getattr(target, '__qualname__', type(target).__qualname__),
        source_sha256=hashlib.sha256(path.read_bytes()).hexdigest() if path is not None and path.is_file() else None,
        runtime_code_sha256=hashlib.sha256(_canonical(_constant(code)).encode('ascii')).hexdigest()
            if code is not None else None,
        identity_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        python_runtime=dict(implementation=sys.implementation.name, version=sys.version))
