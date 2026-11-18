"""Freeze original Bank draw approval and actual registered approval for formal execution input."""
from integration.lifecycle_v5_bank_internal_reception import build_input, run_reception
from integration.lifecycle_v5_bank_internal_reception import main as _main


def build_v5_bank_draw_execution_input(*, draw_result_path, bank_input_path, draw_basis_path,
        approval_path, execution_arrangement_path, output_path):
    return build_input(paths=(draw_result_path, bank_input_path, draw_basis_path, approval_path, execution_arrangement_path),
        output_path=output_path, route='draw')


def run_v5_bank_draw_execution(*, input_path, output_directory, execute=False):
    return run_reception(input_path=input_path, output_directory=output_directory, execute=execute, route='draw')


def main():
    _main('draw')


if __name__ == '__main__':
    main()
