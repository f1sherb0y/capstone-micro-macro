"""Assemble actual Owner draw instruction and received request for formal Bank approval input."""
from integration.lifecycle_v5_owner_bank_reception import build_input, run_reception
from integration.lifecycle_v5_owner_bank_reception import main as _main


def build_v5_owner_draw_bank_input(*, owner_result_path, bank_input_path, reception_path, output_path):
    return build_input(source_result_path=owner_result_path, recipient_input_path=bank_input_path,
        reception_path=reception_path, output_path=output_path, route='draw_request')


def run_v5_owner_draw_bank(*, input_path, output_directory, execute=False):
    return run_reception(input_path=input_path, output_directory=output_directory, execute=execute, route='draw_request')


def main():
    _main('draw_request')


if __name__ == '__main__':
    main()
