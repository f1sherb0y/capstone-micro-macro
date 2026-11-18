"""Assemble actual Bank offers and registered reception for formal Owner financing input."""
from integration.lifecycle_v5_owner_bank_reception import build_input, run_reception
from integration.lifecycle_v5_owner_bank_reception import main as _main


def build_v5_bank_quote_owner_input(*, bank_result_path, owner_input_path, reception_path, output_path):
    return build_input(source_result_path=bank_result_path, recipient_input_path=owner_input_path,
        reception_path=reception_path, output_path=output_path, route='offer')


def run_v5_bank_quote_owner(*, input_path, output_directory, execute=False):
    return run_reception(input_path=input_path, output_directory=output_directory, execute=execute, route='offer')


def main():
    _main('offer')


if __name__ == '__main__':
    main()
