import json

import pytest

from backend.can.signal_sender import SignalSender
from backend.dbc_workspace import DbcWorkspace
from backend.storage import WorkspaceStore
from test_workspace_status import dbc


def workspace_at(directory):
    return DbcWorkspace(WorkspaceStore(directory), SignalSender())


def test_program_favorites_round_trip_with_notes_and_exact_dbc_identity(tmp_path):
    source = workspace_at(tmp_path / 'source')
    first = dbc()
    second = dbc().replace(b'VERSION ""', b'VERSION "second definition"')
    first_id, second_id = source.upload([('one.dbc', first), ('two.dbc', second)])['uploaded_ids']
    source.favorite(first_id, 'Angles', 'PitchAngle', True)
    source.set_signal_note(first_id, 'Angles', 'PitchAngle', 'Default program only')
    source.create_program('ORP')
    source.favorite(first_id, 'Angles', 'PitchAngle', True)
    source.set_signal_note(first_id, 'Angles', 'PitchAngle', 'Tilt check\nExpected pitch: 10°')
    source.favorite(second_id, 'Angles', '', True)
    source.set_signal_note(second_id, 'Angles', 'PitchAngle', 'Whole-message bookmark')

    reopened = workspace_at(tmp_path / 'source')
    package = json.loads(json.dumps(reopened.export_favorites()))
    assert package['program'] == 'ORP'
    assert {entry['note'] for entry in package['entries']} == {
        '', 'Tilt check\nExpected pitch: 10°', 'Whole-message bookmark'}
    assert sum(entry['favorite'] for entry in package['entries']) == 2

    recipient = workspace_at(tmp_path / 'recipient')
    recipient.upload([('renamed-one.dbc', first)])
    recipient.create_program('Team ORP')
    with pytest.raises(ValueError, match=r'matching DBC version\(s\).*two\.dbc'):
        recipient.import_favorites(package)
    assert recipient.state()['favorites'] == []
    assert recipient.state()['signal_notes'] == []

    recipient.upload([('renamed-two.dbc', second)])
    recipient.activate([first_id])
    result = recipient.import_favorites(package)
    assert result == {'favorites_added': 2, 'notes_added': 2, 'notes_kept': 0,
                      'inactive_dbcs': ['renamed-two.dbc']}
    assert recipient.export_favorites()['program'] == 'Team ORP'
    assert recipient.store.program_dbc_ids(recipient.store.active_program()) == [first_id]
    recipient.set_signal_note(first_id, 'Angles', 'PitchAngle', 'Local instructions')
    result = recipient.import_favorites(package)
    assert result['favorites_added'] == result['notes_added'] == 0
    assert result['notes_kept'] == 1
    assert any(note['note'] == 'Local instructions' for note in recipient.state()['signal_notes'])
    assert recipient.select_program('default')['signal_notes'] == []


def test_notes_follow_signal_independently_of_star_and_can_be_removed(tmp_path):
    source = workspace_at(tmp_path)
    dbc_id = source.upload([('one.dbc', dbc())])['uploaded_ids'][0]
    source.favorite(dbc_id, 'Angles', 'PitchAngle', True)
    source.set_signal_note(dbc_id, 'Angles', 'PitchAngle', '  Bench setup  ')
    source.favorite(dbc_id, 'Angles', 'PitchAngle', False)
    assert source.state()['signal_notes'][0]['note'] == 'Bench setup'
    assert source.export_favorites()['entries'] == []
    with pytest.raises(ValueError, match='Signal not found'):
        source.set_signal_note(dbc_id, 'Angles', 'Unknown', 'text')
    source.set_signal_note(dbc_id, 'Angles', 'PitchAngle', '')
    assert source.state()['signal_notes'] == []
