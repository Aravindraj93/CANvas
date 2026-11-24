"""Strict, side-effect-free scenario validation before any connection or send."""
from __future__ import annotations

import math
from pathlib import PureWindowsPath
import yaml

FIELDS = {
    'send_signal': ({'message', 'signal', 'value'}, {'dbc_id'}),
    'send_message': ({'message', 'signals'}, {'dbc_id'}),
    'wait': ({'ms'}, set()),
    'assert_signal': ({'message', 'signal', 'expected'}, {'dbc_id', 'max_age_ms', 'tolerance'}),
    'assert_visual': ({'baseline'}, {'threshold'}),
    'log': ({'message'}, set()),
}


def number(value, name, minimum=None, maximum=None, integer=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or (integer and not isinstance(value, int))
            or (minimum is not None and value < minimum)
            or (maximum is not None and value > maximum)):
        raise ValueError(f'{name}: invalid numeric value {value!r}')


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name}: use a nonempty string')


def parse_scenario(content):
    if not isinstance(content, str) or len(content.encode('utf-8')) > 1_000_000:
        raise ValueError('Scenario must be text of at most 1 MB')
    try:
        config = yaml.safe_load(content)
    except (yaml.YAMLError, RecursionError) as exc:
        raise ValueError(f'Invalid YAML: {exc}') from exc
    validate_scenario(config)
    return config


def validate_scenario(config):
    if not isinstance(config, dict):
        raise ValueError("Test YAML must be a mapping with 'name' and 'steps'")
    if set(config) - {'name', 'description', 'bus', 'steps'}:
        raise ValueError('Unknown scenario fields: ' + ', '.join(map(str, set(config) - {'name', 'description', 'bus', 'steps'})))
    text(config.get('name'), 'name')
    for key in ('description', 'bus'):
        if key in config: text(config[key], key)
    steps = config.get('steps')
    if not isinstance(steps, list) or not 1 <= len(steps) <= 10000:
        raise ValueError('steps must contain between 1 and 10000 steps')
    for index, step in enumerate(steps):
        prefix = f'Step {index + 1}'
        if not isinstance(step, dict): raise ValueError(f'{prefix}: expected a mapping')
        action = step.get('action')
        if not isinstance(action, str) or action not in FIELDS:
            raise ValueError(f'{prefix}: unknown action {action!r}')
        required, optional = FIELDS[action]
        if required - step.keys(): raise ValueError(f'{prefix}: missing {sorted(required - step.keys())}')
        unknown = step.keys() - required - optional - {'action', 'description'}
        if unknown: raise ValueError(f'{prefix}: unknown fields {list(unknown)}')
        for key in ('message', 'signal', 'dbc_id', 'description', 'baseline'):
            if key in step: text(step[key], f'{prefix}.{key}')
        for key in ('value', 'expected'):
            if key in step:
                if isinstance(step[key], str): text(step[key], f'{prefix}.{key}')
                else: number(step[key], f'{prefix}.{key}')
        if 'signals' in step:
            if not isinstance(step['signals'], dict) or not step['signals']:
                raise ValueError(f'{prefix}.signals must be a nonempty mapping')
            for name, value in step['signals'].items():
                text(name, f'{prefix}.signal')
                if isinstance(value, str): text(value, f'{prefix}.{name}')
                else: number(value, f'{prefix}.{name}')
        for key in ('ms', 'max_age_ms'):
            if key in step: number(step[key], f'{prefix}.{key}', 0 if key == 'ms' else 1, 3_600_000, integer=True)
        if 'tolerance' in step: number(step['tolerance'], f'{prefix}.tolerance', 0)
        if 'threshold' in step: number(step['threshold'], f'{prefix}.threshold', 0, 1)
        if 'baseline' in step:
            name = step['baseline']
            if name in ('.', '..') or '/' in name or '\\' in name or PureWindowsPath(name).drive:
                raise ValueError(f'{prefix}.baseline: use a name, not a path')


def validate_definitions(config, sender):
    """Resolve every referenced field and range before an earlier step can send."""
    from backend.can.signal_sender import _signal_value, _valid_signal_value
    for index, step in enumerate(config['steps']):
        if step['action'] not in ('send_signal', 'send_message', 'assert_signal'): continue
        try:
            _, msg = sender.resolve_message(step['message'], step.get('dbc_id'))
            values = step['signals'] if step['action'] == 'send_message' else {
                step['signal']: step['expected'] if step['action'] == 'assert_signal' else step['value']}
            for name, value in values.items():
                sig = msg.get_signal_by_name(name)
                if not _valid_signal_value(sig, _signal_value(sig, value)):
                    raise ValueError(f'{name}: value outside DBC range or choices')
        except (ValueError, KeyError, RuntimeError) as exc:
            raise ValueError(f'Step {index + 1}: {exc}') from exc
    sender.validate_sequence(config['steps'])

