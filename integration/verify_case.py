"""Run a real case and retain evidence of signed contracts and construction."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from integration.case_runner import CaseRunner
from integration.catalog import ROOT
from integration.sessions import atomic_json


class AcceptanceRunner(CaseRunner):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.observations = []
        self.last_recorded_tick = None
        files = [*ROOT.glob('integration/*.py'), *ROOT.glob('src/**/*.py'), *ROOT.glob('prompts/**/*.md')]
        atomic_json(self.directory / 'source_manifest.json', {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files
        })

    def save_result(self):
        result = super().save_result()
        if not self.engine:
            return result
        if self.engine.current_tick != self.last_recorded_tick:
            for project in self.engine.projects.values():
                contracts = project.flags.get('package_contracts', {})
                self.observations.append({
                    'tick': self.engine.current_tick, 'project_id': project.project_id,
                    'stage': project.current_stage.value, 'progress': project.performance.actual_progress,
                    'cost': project.performance.actual_cost,
                    'signed_packages': list(contracts),
                    'construction_packages': [key for key, c in contracts.items() if c['kind'] == 'construction'],
                    'all_signatures_accepted': bool(contracts) and all(all(c['signatures'].values()) for c in contracts.values()),
                    'occupied_resources': {key: agent.occupied_resource for key, agent in self.engine.agents.items()
                                           if agent.occupied_resource > 0},
                    'package_progress': {key: item['performance']['actual_progress']
                                         for key, item in project.flags.get('package_execution', {}).items()},
                })
            self.last_recorded_tick = self.engine.current_tick
            atomic_json(self.directory / 'execution_trace.json', self.observations)
        progressed = [row for row in self.observations if row['stage'] == 'construction' and row['progress'] > 0]
        checks = {
            'real_model': self.settings['mode'] == 'llm',
            'no_terminal_technical_error': self.state['status'] != 'error',
            'signed_multiple_construction_packages': any(len(r['construction_packages']) >= 2 and r['all_signatures_accepted'] for r in progressed),
            'construction_resources_occupied': any(r['occupied_resources'] for r in progressed),
            'multiple_packages_progressed': any(sum(v > 0 for v in r['package_progress'].values()) >= 2 for r in progressed),
            'progress_increased_over_multiple_ticks': len({r['tick'] for r in progressed}) >= 2
                and max((r['progress'] for r in progressed), default=0) > min((r['progress'] for r in progressed), default=0),
        }
        atomic_json(self.directory / 'acceptance.json', {
            'criterion': 'Real organizational procurement leads to signed multi-package contracts, resource occupation and increasing construction progress',
            'passed': all(checks.values()), 'checks': checks, 'status': self.state['status'],
            'first_construction_progress': progressed[0] if progressed else None,
            'last_observation': self.observations[-1] if self.observations else None,
        })
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', default='CASE-0005')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--input', type=Path, help='Use an explicit approved shared input; preserve its procurement plan')
    parser.add_argument('--offline', action='store_true', help='Verify the evidence recorder without model calls')
    args = parser.parse_args()
    runner = AcceptanceRunner(args.output, case_id=args.case, mode='offline' if args.offline else 'llm', input_path=args.input)
    runner.execute()
    print(json.dumps(runner.status(), ensure_ascii=False))
    verdict = json.loads((args.output / 'acceptance.json').read_text(encoding='utf-8')) if runner.engine else {'passed': False}
    raise SystemExit(0 if verdict['passed'] else 1)


if __name__ == '__main__':
    main()
