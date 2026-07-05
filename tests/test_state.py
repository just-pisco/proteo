from proteo.core.state import SessionState, clear, load, save


def make_state():
    return SessionState(virtual_output="DVI-I-1", helper_pid=1234,
                        edid_path="/run/user/1000/proteo/edid.bin",
                        request={"width": 1920, "height": 1080, "fps": 60,
                                 "hdr": False},
                        snapshot={"outputs": []})


def test_roundtrip(tmp_path):
    p = tmp_path / "session.json"
    save(make_state(), p)
    loaded = load(p)
    assert loaded == make_state()


def test_load_missing_and_corrupt(tmp_path):
    assert load(tmp_path / "nope.json") is None
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    assert load(p) is None
    p.write_text('{"unrelated": true}')
    assert load(p) is None


def test_clear_idempotent(tmp_path):
    p = tmp_path / "session.json"
    save(make_state(), p)
    clear(p)
    assert load(p) is None
    clear(p)  # second clear must not raise
