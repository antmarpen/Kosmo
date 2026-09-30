"""Compose recovery smoke check. Requires requests, Docker CLI, and seeded stack."""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = os.getenv("KOSMO_API_URL", "http://localhost:8000")


def request(path, token=None, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read()) if response.status != 204 else None


def main():
    checks = []
    def check(label, passed, detail=""):
        checks.append((label, bool(passed), detail))
        print(f"{'PASS' if passed else 'FAIL'}: {label}{': ' + detail if detail else ''}")

    credentials = {"username": os.getenv("KOSMO_E2E_USERNAME", "test-runner"),
                   "password": os.getenv("KOSMO_E2E_PASSWORD", "runner-change-me")}
    auth = request("/auth/login", payload=credentials)
    token = auth["access_token"]
    check("login", bool(token))
    workflows = request("/workflows", token)
    rows = workflows if isinstance(workflows, list) else workflows.get("items", [])
    workflow = next(item for item in rows if item.get("name") == "reference-security-analysis")
    created = request("/tasks", token, {"workflow_id": workflow["id"], "input_values": {"topic": "recovery-check"}})
    task_id = created["id"]
    check("task submitted", created.get("state") == "queued", task_id)
    detail = None
    deadline = time.time() + 180
    while time.time() < deadline:
        detail = request(f"/tasks/{task_id}", token)
        task = detail.get("task", detail)
        nodes = task.get("node_executions", task.get("nodes", []))
        if any((n.get("node_id", n.get("id")) == "collect" and n.get("state") == "success") for n in nodes):
            break
        time.sleep(2)
    check("script node completed before restart", bool(nodes and any(n.get("node_id", n.get("id")) == "collect" and n.get("state") == "success" for n in nodes)))
    before = {n.get("node_id", n.get("id")): n.get("attempt", 1) for n in nodes if n.get("state") == "success"}
    subprocess.run(["docker", "compose", "restart", "worker"], check=True, timeout=120)
    check("worker restarted", True)
    deadline = time.time() + 180
    while time.time() < deadline:
        detail = request(f"/tasks/{task_id}", token)
        task = detail.get("task", detail)
        nodes = task.get("node_executions", task.get("nodes", []))
        if task.get("state") in {"success", "failed", "stopped"}:
            break
        time.sleep(2)
    terminal = task.get("state") in {"success", "failed", "stopped"}
    check("task reached terminal state", terminal, task.get("state", "unknown"))
    after = {n.get("node_id", n.get("id")): n.get("attempt", 1) for n in nodes if n.get("state") == "success"}
    unchanged = all(after.get(node) == attempt for node, attempt in before.items())
    check("previously completed nodes were not re-executed", unchanged, f"before={before}; after={after}")
    cp = subprocess.run(["docker", "compose", "exec", "-T", "worker", "cat", f"/var/lib/kosmo/tasks/{task_id}/checkpoint.json"], capture_output=True, text=True)
    check("checkpoint file readable", cp.returncode == 0, cp.stderr.strip())
    if cp.returncode == 0:
        checkpoint = json.loads(cp.stdout)
        check("checkpoint contains prior script completion", any(key.startswith("collect:") for key in checkpoint.get("completed", {})))
        completed = checkpoint.get("completed", {})
        executions = task.get("node_executions", task.get("nodes", []))
        successful = {f"{n.get('node_id', n.get('id'))}:{n.get('iteration', 0)}" for n in executions if n.get("state") == "success"}
        check("checkpoint matches successful node executions", successful.issubset(set(completed)),
              f"executions={sorted(successful)}; checkpoint={sorted(completed)}")
    artifacts = request(f"/tasks/{task_id}/artifacts", token)
    hashes_ok = True
    for artifact in artifacts:
        download = urllib.request.Request(f"{BASE}/tasks/{task_id}/artifacts/{artifact['id']}/download",
                                          headers={"Authorization": f"Bearer {token}"})
        import hashlib
        with urllib.request.urlopen(download, timeout=30) as response:
            actual = hashlib.sha256(response.read()).hexdigest()
        hashes_ok &= actual == artifact.get("sha256")
    check("persisted artifact hashes verify after recovery", bool(artifacts) and hashes_ok,
          f"verified={len(artifacts)}")
    print("NOTE: the artifact-persisted / checkpoint-not-yet-published instant is not externally deterministic to force in this smoke script; recovery convergence is covered by worker reconciliation tests, not claimed as a live crash-window proof.")
    sys.exit(0 if all(ok for _, ok, _ in checks) else 1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAIL: recovery scenario aborted: {type(exc).__name__}: {exc}")
        raise
