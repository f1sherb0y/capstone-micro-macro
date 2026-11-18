"""Assemble original Owner offer acceptance and actual reception for independent Bank arrangement."""
from integration.lifecycle_v5_owner_bank_reception import build_input, run_reception
from integration.lifecycle_v5_owner_bank_reception import main as _main


def build_v5_owner_acceptance_bank_input(*, owner_result_path, bank_input_path, reception_path, output_path):
    return build_input(source_result_path=owner_result_path, recipient_input_path=bank_input_path,
        reception_path=reception_path, output_path=output_path, route='acceptance')


def run_v5_owner_acceptance_bank(*, input_path, output_directory, execute=False):
    return run_reception(input_path=input_path, output_directory=output_directory, execute=execute, route='acceptance')


def main():
    _main('acceptance')


if __name__ == '__main__':
    main()
