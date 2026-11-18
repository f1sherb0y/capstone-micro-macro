"""Read exact existing Supplier result evidence without opening a writable store."""
from contextlib import closing
from pathlib import Path
import sqlite3

from integration.scenario_v2 import parse_input_json
from src.coordination.tasks import task_digest


def read_original_supplier_result(*, journal_path, output, identity):
    tables = {'SUPPLIER-A04': 'supplier_order_results', 'SUPPLIER-A05': 'supplier_planning_results', 'SUPPLIER-A06': 'supplier_execution_results',
        'SUPPLIER-A07': 'supplier_quality_results', 'SUPPLIER-A08': 'supplier_logistics_results'}
    table = tables.get(identity.action_id)
    journal = Path(journal_path).resolve()
    evidence = output['execution_evidence']
    if (table is None or not journal.is_file() or evidence['result_table'] != table
            or output.get('source_mode') != 'fixture' or output.get('macro_execution') != 'not_performed'
            or evidence.get('model_host') is not None):
        raise ValueError('Supplier result requires an existing original offline journal and supported action')
    with closing(sqlite3.connect(journal.as_uri() + '?mode=ro', uri=True)) as db:
        row = db.execute('SELECT record FROM ' + table + ' WHERE task_key=?', (identity.key,)).fetchone()
        task_row = db.execute('SELECT record FROM tasks WHERE key=?', (identity.key,)).fetchone()
    if row is None or task_row is None:
        raise ValueError('Supplier source lacks its original saved result or durable task')
    _, record = parse_input_json(row[0].encode('utf-8'))
    _, task = parse_input_json(task_row[0].encode('utf-8'))
    if (record['identity'] != identity.as_dict() or record['result']['kind'] != 'completed'
            or record['result'] != output['result'] or record['audit'] != evidence['saved_audit']
            or record['record_sha256'] != evidence['record_sha256']
            or record['result_sha256'] != task_digest(record['result'])
            or record['source_reading_sha256'] != task_digest(record['source_reading'])
            or record['source_reading_sha256'] != evidence['source_reading_sha256']
            or task_digest({key: value for key, value in record.items() if key != 'record_sha256'}) != record['record_sha256']
            or task['identity'] != identity.as_dict() or task['state'] != 'output_formed'
            or task['output'] != record['result'] or task['output_sha256'] != record['result_sha256']
            or task['submission'] is not None or task['receipt'] is not None
            or any(task.get(key) != evidence['task'].get(key) for key in
                ('identity', 'state', 'output', 'output_sha256', 'submission', 'receipt'))):
        raise ValueError('Supplier source changes original journal result, audit, reading or durable output')
    return record
