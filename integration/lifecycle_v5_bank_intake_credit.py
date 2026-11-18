"""Freeze original accepted Bank intake and actual review-task lineage for formal credit input."""
from integration.lifecycle_v5_bank_internal_reception import _prepare_data, build_input, run_reception
from integration.lifecycle_v5_bank_internal_reception import main as _main


def build_v5_bank_intake_credit_input(*, intake_result_path, bank_input_path, intake_basis_path, native_intake_path, output_path):
    return build_input(paths=(intake_result_path, bank_input_path, intake_basis_path, native_intake_path),
        output_path=output_path, route='intake')


def run_v5_bank_intake_credit(*, input_path, output_directory, execute=False):
    return run_reception(input_path=input_path, output_directory=output_directory, execute=execute, route='intake')


def main():
    _main('intake')


if __name__ == '__main__':
    main()
