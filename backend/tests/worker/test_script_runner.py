import json
from pathlib import Path

import pytest

from worker.script_runner import run_descriptor


def _descriptor(tmp_path, code, inputs=None, outputs=("result",)):
    input_dir = tmp_path / "inputs"
    output_dir = tmp_path / "output"
    input_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)
    descriptors = {}
    for name, (media_type, content) in (inputs or {}).items():
        path = input_dir / name
        path.write_text(content, encoding="utf-8")
        descriptors[name] = {"media_type": media_type, "path": str(path)}
    descriptor = {"source": code, "input_names": list(descriptors), "inputs": descriptors,
                  "output_names": list(outputs), "output_dir": str(output_dir)}
    path = tmp_path / "descriptor.json"
    path.write_text(json.dumps(descriptor), encoding="utf-8")
    return path, output_dir


def test_runs_body_with_typed_json_input_and_writes_manifest(tmp_path):
    descriptor, output = _descriptor(tmp_path, "answer = data['n'] + 1\nreturn answer",
                                     {"data": ("application/json", '{"n": 4}')}, ("answer",))

    run_descriptor(descriptor)

    assert json.loads((output / "answer").read_text()) == 5
    assert json.loads((output / "manifest.json").read_text()) == {"answer": "application/json"}


def test_serializes_strings_as_plain_text_and_json_values(tmp_path):
    descriptor, output = _descriptor(tmp_path, "text = 'hello'\nvalue = [1, 2]\nreturn text, value",
                                     outputs=("text", "value"))
    run_descriptor(descriptor)
    assert (output / "text").read_text() == "hello"
    assert json.loads((output / "manifest.json").read_text()) == {
        "text": "text/plain", "value": "application/json"}


@pytest.mark.parametrize("code", ["return", "return 1", "return a, b"])
def test_rejects_return_contract_mismatch(tmp_path, code):
    descriptor, _ = _descriptor(tmp_path, code, outputs=("a",))
    with pytest.raises(ValueError):
        run_descriptor(descriptor)


def test_rejects_non_finite_json_values(tmp_path):
    descriptor, _ = _descriptor(tmp_path, "result = float('inf')\nreturn result")
    with pytest.raises(ValueError):
        run_descriptor(descriptor)


def test_rejects_escaping_or_symlink_output_paths(tmp_path):
    descriptor, output = _descriptor(tmp_path, "return result")
    try:
        (output / "result").symlink_to(tmp_path / "outside")
    except OSError:
        pytest.skip("Symlink creation is not permitted on this host")
    with pytest.raises(ValueError):
        run_descriptor(descriptor)


def test_rejects_unsupported_input_media_type(tmp_path):
    descriptor, _ = _descriptor(tmp_path, "return value",
                                {"value": ("image/png", "not parsed")}, ("value",))
    with pytest.raises(ValueError):
        run_descriptor(descriptor)
