from geniac_visualizer.health import Health

def test_deadline_cooldown_and_recovery():
    h=Health(0)
    assert not h.due(['camera','scenario'],29)
    h.seen('camera',31)
    assert h.due(['camera','scenario'],31)==['scenario']
    assert not h.due(['camera','scenario'],40)
    h.seen('camera',150);h.seen('scenario',150)
    assert not h.due(['camera','scenario'],151)
    assert h.due(['camera','scenario'],181)==['camera','scenario']
