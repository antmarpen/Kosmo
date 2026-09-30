from worker.activities.sandbox import script_failure


def test_script_failure_public_error_does_not_include_raw_traceback_or_output():
    failure = script_failure(1)

    assert failure == {
        "state": "failed",
        "error": {
            "code": "SCRIPT_FAILED",
            "message_key": "errors.script.failed",
            "params": {"exit_code": 1},
        },
    }
    assert "Traceback" not in str(failure)
    assert "RuntimeError" not in str(failure)
