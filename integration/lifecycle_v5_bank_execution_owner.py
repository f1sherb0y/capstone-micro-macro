"""Assemble and explicitly consume actual Bank reconciliation in a formal Owner input."""
from integration.lifecycle_v5_owner_bank_reception import _prepare_data, _read, build_input, run_reception
from integration.lifecycle_v5_owner_bank_reception import main as _main


_SCHEMA = 'lifecycle-v5-bank-execution-owner-input.v1'


def build_v5_bank_execution_owner_input(*, bank_result_path, owner_input_path, reception_path, output_path):
    return build_input(source_result_path=bank_result_path, recipient_input_path=owner_input_path,
        reception_path=reception_path, output_path=output_path, route='execution')


def run_v5_bank_execution_owner(*, input_path, output_directory, execute=False):
    return run_reception(input_path=input_path, output_directory=output_directory, execute=execute, route='execution')


def main():
    _main('execution')


if __name__ == '__main__':
    main()
