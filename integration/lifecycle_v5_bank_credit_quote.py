"""Freeze original Bank credit review and independently recorded assessment for formal quotation."""
from integration.lifecycle_v5_bank_internal_reception import build_input, run_reception
from integration.lifecycle_v5_bank_internal_reception import main as _main


def build_v5_bank_credit_quote_input(*, credit_result_path, bank_input_path, credit_basis_path,
        assessment_path, recorded_review_path, output_path):
    return build_input(paths=(credit_result_path, bank_input_path, credit_basis_path, assessment_path, recorded_review_path),
        output_path=output_path, route='credit')


def run_v5_bank_credit_quote(*, input_path, output_directory, execute=False):
    return run_reception(input_path=input_path, output_directory=output_directory, execute=execute, route='credit')


def main():
    _main('credit')


if __name__ == '__main__':
    main()
