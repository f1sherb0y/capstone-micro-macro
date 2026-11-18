"""Retain original Bank execution and actual observations for formal existing-command reconciliation."""
from integration.lifecycle_v5_bank_internal_reception import build_input, run_reception
from integration.lifecycle_v5_bank_internal_reception import main as _main


def build_v5_bank_execution_reconcile_input(*, execution_result_path, bank_input_path, observation_path, output_path):
    return build_input(paths=(execution_result_path, bank_input_path, observation_path),
        output_path=output_path, route='execution')


def run_v5_bank_execution_reconcile(*, input_path, output_directory, execute=False):
    return run_reception(input_path=input_path, output_directory=output_directory, execute=execute, route='execution')


def main():
    _main('execution')


if __name__ == '__main__':
    main()
