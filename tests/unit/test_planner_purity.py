"""Planner import/execution checks with environment, clock and I/O unavailable."""

import ast
import inspect
import subprocess
import sys
from pathlib import Path

import packages.planner.policy
from packages.domain import PlannerAction
from tests.unit.test_planner_policy import diagnostic, directive, frame, review, run, state, topic


def test_planner_source_imports_only_domain_and_pure_standard_library() -> None:
    directory = Path(inspect.getfile(packages.planner.policy)).parent
    allowed = {"hashlib", "typing", "uuid", "packages.domain", "packages.planner"}
    forbidden_calls = {
        "open", "eval", "exec", "uuid1", "uuid3", "uuid4", "uuid5", "now", "utcnow", "getenv",
    }
    for source in directory.glob("*.py"):
        tree = ast.parse(source.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                names = []
            assert all(any(name == root or name.startswith(root + ".") for root in allowed)
                       for name in names), (source, names)
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else (
                    node.func.attr if isinstance(node.func, ast.Attribute) else ""
                )
                assert name not in forbidden_calls, (source, name)


def test_import_and_planning_work_without_infrastructure_or_environment() -> None:
    states = [
        state(session_complete=True), state(user_paused=True), state(budget_exceeded=True),
        state(directives=(directive(),)), state(review_candidates=(review(),)),
        state(remediation_frame=frame()), state(remediation_frame=frame(complete=True)),
        state(topic=topic()), state(topic=topic(taught=True)),
        state(topic=topic(taught=True, checked=True)),
        state(topic=topic(taught=True, checked=True, quiz_completed=True,
                          gate_satisfied=True, next_topic_id=state().graph_context.topic_ids[1])),
        state(diagnostic_state=run(), diagnostic_candidates=(diagnostic(),)),
        state(graph_context=None), state(hard_stop=PlannerAction.TEACH_CURRENT_TOPIC),
    ]
    root = str(Path(__file__).resolve().parents[2])
    serialized = [item.model_dump_json() for item in states]
    script = f"""
import datetime, importlib.abc, os, random, secrets, socket, sys, time, uuid
sys.path.insert(0, {root!r})
class NoInfrastructure(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {{'sqlalchemy', 'redis', 'minio', 'httpx', 'requests'}} \
                or fullname.startswith(('packages.persistence', 'packages.mastery',
                    'packages.curriculum', 'packages.agents', 'packages.model_client',
                    'packages.retrieval', 'packages.evalkit', 'apps.')):
            raise AssertionError('Infrastructure import: ' + fullname)
sys.meta_path.insert(0, NoInfrastructure())
from packages.domain import PlanningState
from packages.planner import PlannerPolicy
states = [PlanningState.model_validate_json(value) for value in {serialized!r}]
def forbidden(*args, **kwargs):
    raise AssertionError('Planner attempted environment, clock, randomness or network access')
os.environ.clear()
os.getenv = forbidden
class NoEnvironment(dict):
    __getitem__ = get = __iter__ = forbidden
os.environ = NoEnvironment()
class NoClock(datetime.datetime):
    now = utcnow = forbidden
datetime.datetime = NoClock
time.time = time.monotonic = time.perf_counter = forbidden
random.random = random.choice = secrets.token_bytes = uuid.uuid4 = forbidden
socket.create_connection = forbidden
def audit(event, args):
    if event in {{'open', 'socket.connect', 'subprocess.Popen', 'os.listdir', 'os.scandir'}}:
        raise AssertionError('Planner attempted I/O: ' + event)
sys.addaudithook(audit)
print('|'.join(PlannerPolicy.decide(state).canonical_bytes().hex() for state in states))
"""
    outputs = []
    for seed in ("1", "42"):
        completed = subprocess.run(
            [sys.executable, "-P", "-s", "-c", script], cwd=root,
            env={"PYTHONHASHSEED": seed}, capture_output=True, text=True, timeout=20,
        )
        assert completed.returncode == 0, completed.stderr
        outputs.append(completed.stdout)
    assert outputs[0] == outputs[1]
