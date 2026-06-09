import pytest
from server import runner

def test_run_script_captures_output():
    rc, out, err = runner.run_script(["-c", "print('hi')"])
    assert rc == 0
    assert out.strip() == "hi"

def test_validation_ok_treats_2_as_pass():
    assert runner.validation_ok(0) is True
    assert runner.validation_ok(2) is True   # warnings = pass
    assert runner.validation_ok(1) is False  # only 1 fails

def test_lock_rejects_reentry():
    with runner.run_lock():
        with pytest.raises(runner.Busy):
            with runner.run_lock():
                pass
