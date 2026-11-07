"""One authorized verification invocation; artifacts only, no source edits."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import stat
import subprocess
import time
from datetime import datetime, timezone

ROOT = Path('/root/Code/slo-message-queue/slo')
OUT = Path(__file__).resolve().parent
PREP = ROOT / 'release-evidence/96-cooperative-provider-tool-yield/full-suite-verification-20261105T042944Z-1005245/proposed-command.txt'

def stamp():
    return datetime.now(timezone.utc).isoformat()

def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, sort_keys=True))

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)

def snapshot(label):
    names = git('ls-files', '-z', '--cached', '--others', '--exclude-standard').decode().split('\0')
    names += ['RESEARCH.md'] if (ROOT / 'RESEARCH.md').exists() else []
    files = {}
    for name in sorted(set(names)):
        if not name or name.startswith('release-evidence/'): continue
        p = ROOT / name
        if not p.exists() and not p.is_symlink():
            files[name] = {'missing': True}
            continue
        s = p.lstat()
        files[name] = {'mode': stat.S_IMODE(s.st_mode), 'link': os.readlink(p) if p.is_symlink() else None,
                       'sha256': hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None}
    save(label + '-manifest.json', files)
    (OUT / (label + '-git-status.txt')).write_bytes(git('status', '--short'))
    (OUT / (label + '-git-diff.patch')).write_bytes(git('diff', 'HEAD', '--', '.', ':!release-evidence'))
    utilities = {}
    # Snapshot every installed coreutils executable, plus the interpreter.
    paths = subprocess.check_output(['/usr/bin/dpkg-query', '-L', 'coreutils']).decode().splitlines()
    paths += ['/root/.pyenv/versions/slo-harness/bin/python']
    for path in paths:
        p = Path(path)
        if not p.is_file() or not os.access(p, os.X_OK): continue
        s = p.stat()
        utilities[path] = {'target': str(p.resolve()), 'device': s.st_dev, 'inode': s.st_ino,
                           'mode': stat.S_IMODE(s.st_mode), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
    save(label + '-utilities.json', utilities)
    v = subprocess.run(['/usr/bin/dpkg', '-V', 'coreutils'], capture_output=True)
    (OUT / (label + '-dpkg-coreutils.stdout')).write_bytes(v.stdout)
    (OUT / (label + '-dpkg-coreutils.stderr')).write_bytes(v.stderr)
    save(label + '-dpkg-coreutils-exit.json', v.returncode)
    return files, utilities

def processes():
    result = {}
    for p in Path('/proc').iterdir():
        if not p.name.isdigit(): continue
        try:
            s = (p / 'stat').read_text().rsplit(')', 1)[1].split()
            result[int(p.name)] = {'pid': int(p.name), 'state': s[0], 'ppid': int(s[1]), 'pgid': int(s[2]),
                                   'sid': int(s[3]), 'start': s[19],
                                   'argv': (p / 'cmdline').read_bytes().decode(errors='replace').split('\0')[:-1]}
        except OSError: pass
    return result

os.chdir(ROOT)
ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0)  # Adopt/reap test descendants, never unrelated processes.
save('identity.json', {'cwd': str(ROOT.resolve()), 'head': git('rev-parse', 'HEAD').decode().strip(),
                       'branch': git('branch', '--show-current').decode().strip(), 'started': stamp(),
                       'supervisor_pid': os.getpid(), 'worktree': git('worktree', 'list', '--porcelain').decode()})
lines = PREP.read_text().splitlines()
command = shlex.split(lines[-1])
ignores = [a for a in command if a.startswith('--ignore=')]
deselects = [a for a in command if a.startswith('--deselect=')]
assert len(ignores) == 12 and len(deselects) == 24
save('approved-exclusions.json', {'ignore': ignores, 'deselect': deselects, 'marker': 'not e2e', 'source': str(PREP)})
command += ['--junitxml=' + str(OUT / 'junit.xml')]
env = {k: os.environ[k] for k in ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TERM') if k in os.environ}
env.update(SLO_ENV='test', SLO_ROOT_DIR=str(ROOT), SLO_APP_DIR=str(ROOT), SLO_APP_NAME='slo',
           SLO_LOG_FORMAT='text', SLO_DEFAULT_MODEL_NAME='gpt-5.4', SLO_AUTO_VISUALIZE='0',
           SLO_HERDR_DISABLED='1', SLO_ANTHROPIC_API_KEY='ci-placeholder-tests-are-fully-mocked',
           COLUMNS='120', LINES='40', PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1')
save('environment.json', env)
(OUT / 'exact-command.txt').write_text('cd ' + shlex.quote(str(ROOT)) + '\n' +
    'env -i ' + ' '.join(shlex.quote(k + '=' + v) for k, v in sorted(env.items())) + ' ' + shlex.join(command) + '\n')
(OUT / 'policy.txt').write_text('Makefile test-env resolves fallback (tests.env absent). Authorized explicit fallback matches Makefile. Clean child env prevents inherited real provider credentials and pytest selection overrides. No selection additions except nonselecting JUnit output. One invocation only. Timeout 2400 seconds. Historical PID1261413 inert ep_poll, unchanged CPU/I/O, deleted cwd, deleted output fds; only resource_tracker child1261498 idle pipe read. PID3382468 unrelated historical fake-herdr sleeps. Neither signaled.\n')
before, ubefore = snapshot('before')
initial = processes()
save('prelaunch-processes.json', initial)
owned = {}
p = None
receipt = {'started': stamp(), 'timeout_seconds': 2400, 'command': command}
interrupted = False

def cancel(signum, frame):
    raise KeyboardInterrupt('supervisor signal ' + str(signum))

signal.signal(signal.SIGTERM, cancel)
signal.signal(signal.SIGINT, cancel)

def track():
    live = processes()
    changed = True
    while changed:
        changed = False
        for pid, info in live.items():
            if pid in owned and owned[pid]['start'] == info['start']: continue
            parent = info['ppid']
            if (p is not None and (pid == p.pid or info['pgid'] == p.pid or info['sid'] == p.pid)) or (parent in owned and parent in live and owned[parent]['start'] == live[parent]['start']) or (parent == os.getpid() and pid not in initial):
                owned[pid] = info
                with (OUT / 'descendants.jsonl').open('a') as f:
                    f.write(json.dumps({'observed': stamp(), **info}) + '\n')
                changed = True
    return live

try:
    with (OUT / 'stdout.log').open('wb') as stdout, (OUT / 'stderr.log').open('wb') as stderr:
        p = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
        receipt['pytest_pid'] = p.pid
        start = time.monotonic()
        while True:
            track()
            if p.poll() is not None: break
            if time.monotonic() - start > 2400:
                receipt['timeout'] = True
                break
            time.sleep(0.2)
        receipt['pytest_exit_code'] = p.poll()
        receipt['pytest_elapsed_seconds'] = time.monotonic() - start
except BaseException as exc:
    receipt['supervision_exception'] = repr(exc)
    interrupted = True
finally:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    # Signal only identity-matched descendants; include escaped sessions via tracking/subreaper.
    actions = []
    for sig, wait in ((signal.SIGTERM, 5), (signal.SIGKILL, 3)):
        live = track()
        for pid, info in owned.items():
            current = live.get(pid)
            if current is None or current['start'] != info['start'] or current['state'] == 'Z': continue
            try:
                os.kill(pid, sig)
                actions.append({'pid': pid, 'start': info['start'], 'signal': int(sig)})
            except ProcessLookupError: pass
        until = time.monotonic() + wait
        while time.monotonic() < until:
            if p is not None: p.poll()
            try:
                while os.waitpid(-1, os.WNOHANG)[0]: pass
            except ChildProcessError: pass
            live = track()
            if not any(pid in live and live[pid]['start'] == info['start'] for pid, info in owned.items()): break
            time.sleep(0.1)
    live = track()
    remaining = [live[pid] for pid, info in owned.items() if pid in live and live[pid]['start'] == info['start']]
    save('cleanup.json', {'actions': actions, 'remaining_owned': remaining, 'tracked_identities': len(owned),
                          'historical_unrelated': {str(pid): live.get(pid) for pid in (1261413, 1261498, 3382468)}})
    after, uafter = snapshot('after')
    changed = {name: {'before': before.get(name), 'after': after.get(name)} for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
    save('preservation.json', {'source_changes': changed, 'source_unchanged': not changed,
                               'utilities_unchanged': ubefore == uafter, 'utility_entries': len(ubefore)})
    receipt.update(finished=stamp(), cleanup_remaining=len(remaining), source_unchanged=not changed,
                   utilities_unchanged=ubefore == uafter)
    save('receipt.json', receipt)
    print(json.dumps(receipt, indent=2), flush=True)
