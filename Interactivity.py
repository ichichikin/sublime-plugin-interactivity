import functools
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
from queue import Queue

import sublime
import sublime_plugin


SETTINGS_FILE = 'Interactivity.sublime-settings'
PANEL_NAME = 'interactivity'
PLUGIN_DIR = os.path.dirname(os.path.realpath(__file__)) + os.sep
# plain text and markup languages for notes, except code blocks of programming languages
DEFAULT_SELECTOR = ('text.plain, text.html.markdown - source, text.restructuredtext - source, '
                    'text.orgmode - source, text.asciidoc - source')
# settings that are read when the REPL starts; changing them restarts it
PROCESS_SETTINGS = ('shell', 'shell_params', 'environment_variables', 'enviroment_variables',
                    'startup_commands', 'shutdown_commands', 'lines_to_suppress')
# a message of py_manager.py: JSON on a line that starts with this character
MESSAGE = re.compile('\x1e(\\{[^\\n]*\\})\\n?')
# how long a REPL that doesn't run py_manager.py may keep silent before it gets commands, and how long its greeting
# may pause; py_manager.py may take longer to start (e.g. while an antivirus checks Python)
PROTOCOL_TIMEOUT = 2000
GREETING_PAUSE = 300
STARTUP_TIMEOUT = 30000
# prompts in front of lines copied from a Python console
REPL_PROMPT = re.compile(r'^(?:>>>|\.\.\.)(?: |$)', re.MULTILINE)
# a block in one line (e.g. "for x in y: print(x)"), which the Python REPL only runs after an empty line
ONE_LINE_BLOCK = re.compile(r'\s*(?:(?:if|for|while|with|try|def|class|async)\b.*:|@)')
PARAM = re.compile('##param(_str)?##')
# a string literal around ##param## in shortcuts of older versions, which breaks on quotes and backslashes
OLD_PARAM_STR = re.compile(r'[rR]?("""|\'\'\')##param## ?\1')

repl = None
# False once Sublime Text is shutting down the API
api_available = True
panel_log = []


def settings():
    return sublime.load_settings(SETTINGS_FILE)


def expand(value):
    return str(value).replace('##plugin##', PLUGIN_DIR)


def expand_vars(value, env):
    # $VAR, ${VAR} and, on Windows, %VAR%, as the shell used to expand them
    names = {key.upper(): val for key, val in env.items()} if os.name == 'nt' else env
    pattern = r'\$(\w+)|\$\{([^}]*)\}' + (r'|%([^%]+)%' if os.name == 'nt' else '')

    def replace(match):
        name = next(group for group in match.groups() if group is not None)
        return names.get(name.upper() if os.name == 'nt' else name, match.group(0))

    return os.path.expanduser(re.sub(pattern, replace, value))


def command_line(s, env):
    shell = expand(s.get('shell') or 'python')
    params = [expand_vars(expand(param), env) for param in s.get('shell_params') or []]
    path = env.get('PATH')
    if shell == 'python' and os.name != 'nt':
        # "python" may be Python 2
        found = shutil.which('python3', path=path) or shutil.which('python', path=path)
    else:
        found = shutil.which(expand_vars(shell, env), path=path)
    if found:
        return [found] + params
    if os.name != 'nt':
        if len(shell.split()) > 1:
            # a command line for the shell, as in older versions of the plugin (which ignored "shell_params" then)
            return ['/bin/sh', '-c', shell]
        return [expand_vars(shell, env)] + params
    parts = [part.strip('"') for part in shlex.split(expand_vars(shell, env), posix=False)]
    if len(parts) > 1 and shutil.which(parts[0], path=path):
        # the command line of a program, e.g. "py -3"
        return [shutil.which(parts[0], path=path)] + parts[1:] + params
    return [expand_vars(shell, env)] + params


def environment(s):
    env = os.environ.copy()
    # "enviroment_variables" is the old, misspelled name of the setting; only users set it, so it comes last
    for name in ('environment_variables', 'enviroment_variables'):
        for key, value in (s.get(name) or {}).items():
            # the names are not case-sensitive on Windows, where os.environ has them in upper case
            key = str(key).upper() if os.name == 'nt' else str(key)
            if value is None:
                env.pop(key, None)
            else:
                env[key] = expand(value)
    # the plugin reads the output as UTF-8
    env.setdefault('PYTHONIOENCODING', 'utf-8')
    # py_manager.py also loads the user's modules from this folder, which survives updates of the plugin
    env.setdefault('INTERACTIVITY_USER_MODULES', os.path.join(sublime.packages_path(), 'User', 'Interactivity'))
    return env


def process_settings(s):
    return json.dumps([s.get(name) for name in PROCESS_SETTINGS], sort_keys=True)


def show_panel(window):
    # with everything written to the panel so far, in any window
    window.destroy_output_panel(PANEL_NAME)
    panel = window.create_output_panel(PANEL_NAME)
    panel.run_command('append', {'characters': ''.join(panel_log), 'force': True, 'scroll_to_end': True})
    window.run_command('show_panel', {'panel': 'output.' + PANEL_NAME})


def panel_write(text, show=False):
    panel_log.append(text)
    del panel_log[:-1000]
    window = sublime.active_window()
    if not window.is_valid():   # no window is open
        print(text, end='')
        return
    panel = window.find_output_panel(PANEL_NAME)
    if show and (panel is None or window.active_panel() != 'output.' + PANEL_NAME):
        show_panel(window)
    elif panel is not None:
        panel.run_command('append', {'characters': text, 'force': True, 'scroll_to_end': True})


def report(message, show=False):
    sublime.status_message('Interactivity: ' + message)
    panel_write('Interactivity: {}\n'.format(message), show)


def directory_of(view):
    if view.file_name():
        return os.path.dirname(view.file_name())
    window = view.window()
    folders = window.folders() if window else []
    return folders[0] if folders else None


def shortcut_command(text):
    shortcuts = settings().get('text_shortcuts') or {}
    for key in sorted(shortcuts, key=len, reverse=True):
        if key and text.startswith(key):
            param = text[len(key):]
            template = OLD_PARAM_STR.sub('##param_str##', shortcuts[key])
            return PARAM.sub(lambda m: json.dumps(param, ensure_ascii=False) if m.group(1) else param, template)
    return None


def shortcuts_enabled(view, point):
    enabled = view.settings().get('interactivity_shortcuts')
    if enabled is not None:
        return bool(enabled)
    selector = settings().get('enabled_selector', DEFAULT_SELECTOR)
    return not selector or view.match_selector(point, selector)


def run_jobs(view, edit, jobs):
    """Opens an empty line below every job, puts the caret there and runs the job in the REPL.

    jobs is a list of (end of the job's last line, lines of code) tuples.
    """
    merged = {}
    for line_end, lines in jobs:
        merged.setdefault(line_end, []).extend(lines)
    targets = []
    # bottom up, so that the positions above stay valid
    for line_end in sorted(merged, reverse=True):
        line = view.line(line_end)
        # a line that runs again while it still runs: the new output goes after the output it has so far
        running = repl.running(view, line)
        if running is None:
            view.insert(edit, line_end, '\n')
        targets.append((Target(view, running.point() if running else line_end, line), merged[line_end]))
    if not targets:
        return
    view.sel().clear()
    directory = directory_of(view)
    for target, lines in reversed(targets):
        # below the line (a read-only view has no new line)
        view.sel().add(sublime.Region(min(target.point() + 1, view.size())))
        repl.send(lines, target, directory)
    view.show(view.sel()[0])


class Target:
    """The end of the line a command came from, or of its last line of output, where its next output goes.

    The point moves along with edits, and to a clone of the view when the view is closed. The line of the command
    is kept too.
    """

    count = 0

    def __init__(self, view, point, line):
        Target.count += 1
        self.key = 'interactivity_output_{}'.format(Target.count)
        self.move(view, point, line)

    def move(self, view, point, line):
        self.view = view
        view.add_regions(self.key, [sublime.Region(point)], '', '', sublime.HIDDEN)
        view.add_regions(self.key + '_line', [line], '', '', sublime.HIDDEN)

    def point(self):
        regions = self.view.get_regions(self.key) if self.view.is_valid() else []
        return regions[0].b if regions else None

    def line(self):
        regions = self.view.get_regions(self.key + '_line') if self.view.is_valid() else []
        return regions[0] if regions else None

    def finish(self):
        if self.view.is_valid():
            self.view.erase_regions(self.key)
            self.view.erase_regions(self.key + '_line')


class Repl:
    """The REPL process, and the routing of its output to the places the commands came from.

    With py_manager.py every command is sent in a frame with an id, and py_manager.py tells when each command
    starts and ends. Other REPLs get plain lines, and their output goes to the latest command.
    """

    def __init__(self):
        self.process = None
        self.generation = 0     # changes when a process starts or stops; callbacks of older processes are ignored
        self.writes = None      # input for the writer thread; None closes the REPL's stdin
        self.incoming = None    # output of the REPL waiting for the main thread
        self.reader = None
        self.expect_frames = False  # the REPL runs py_manager.py
        self.greeting = 0       # lines of output of a REPL before it got commands
        self.next_id = 0
        self.snapshot = None
        self.start_time = 0
        self.suppress = 0
        self.shutdown_commands = ''
        self.protocol = None    # None until known, 'frames' for py_manager.py, 'lines' for other REPLs
        self.waiting = []       # commands sent before the protocol is known
        self.targets = {}       # id -> target of the commands sent in frames that haven't ended
        self.started = set()    # ids of the commands that started
        self.current = None     # the target of the output being received; None is the output panel
        self.finished = []      # targets that may be done
        self.batch = []         # output waiting to be written, as (target, lines)

    def start(self, directory=None):
        self.stop()
        s = settings()
        cwd = directory if directory and os.path.isdir(directory) else os.path.expanduser('~')
        args = []
        try:
            env = environment(s)
            args = command_line(s, env)
            suppress = int(s.get('lines_to_suppress') or 0)
            process = subprocess.Popen(
                args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=cwd, env=env, encoding='utf-8', errors='replace', bufsize=1,
                # its own process group, to end everything it started; no console window on Windows
                start_new_session=os.name != 'nt', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, ValueError, TypeError) as e:
            report('cannot start "{}": {}. Check the "shell" setting.'.format(' '.join(args), e), show=True)
            return False
        self.generation += 1
        self.process = process
        self.writes = Queue()
        self.incoming = ([], threading.Lock())
        self._reset()
        # until py_manager.py tells that it's ready, or another REPL has printed its greeting or kept silent for
        # a while, the commands wait
        self.expect_frames = any('py_manager.py' in arg for arg in args)
        self.greeting = 0
        self.snapshot = process_settings(s)
        self.start_time = time.time()
        self.suppress = suppress
        self.shutdown_commands = s.get('shutdown_commands') or ''
        self.reader = threading.Thread(target=self._read_loop, args=(process, self.generation, self.incoming), daemon=True)
        self.reader.start()
        threading.Thread(target=self._write_loop, args=(process, self.writes), daemon=True).start()
        threading.Thread(target=self._wait_loop, args=(process, self.generation, self.reader), daemon=True).start()
        sublime.set_timeout(functools.partial(self._protocol_timeout, self.generation, None),
                            STARTUP_TIMEOUT if self.expect_frames else PROTOCOL_TIMEOUT)
        startup_commands = s.get('startup_commands') or ''
        if startup_commands:
            self._send(startup_commands.split('\n'), None)
        return True

    def stop(self, api=True, wait=False):
        """Closes the REPL's stdin after the shutdown commands, and kills the REPL if it doesn't exit in time."""
        process, self.process = self.process, None
        if process is None:
            return
        self.generation += 1
        if self.shutdown_commands:
            self.writes.put(self.shutdown_commands + '\n')
        self.writes.put(None)
        if wait:
            self._end(process)
        else:
            threading.Thread(target=self._end, args=(process,), daemon=True).start()
        if api:
            self._reset()

    @staticmethod
    def _end(process, timeout=1.0):
        try:
            process.wait(timeout)
        except subprocess.TimeoutExpired:
            if os.name != 'nt':
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except OSError:
                    pass
            else:
                try:
                    # the REPL and the programs it started
                    subprocess.call(['taskkill', '/f', '/t', '/pid', str(process.pid)], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=timeout * 5)
                except (OSError, subprocess.SubprocessError):
                    pass
                try:
                    process.kill()
                except OSError:
                    pass
            try:
                process.wait(timeout)
            except subprocess.TimeoutExpired:
                pass

    def send(self, lines, target=None, directory=None):
        if self.process is not None and self.process.poll() is not None:
            # the REPL exited: its last output and its exit come first
            self.reader.join(0.5)
            self._deliver(self.generation)
            self._on_exit(self.generation, self.process.returncode)
        if self.process is None:
            restart = self.generation > 0
            if not self.start(directory):
                if target is not None:
                    target.finish()
                return
            if restart:
                sublime.status_message('Interactivity: the REPL was restarted')
        self._send(lines, target, directory)

    def running(self, view, line):
        """The target of the latest command from this line of the view that hasn't ended, if any."""
        found = None
        for target in list(self.targets.values()) + [target for _, target, _ in self.waiting]:
            if target is not None and target.view == view and target.line() == line \
                    and (found is None or target.point() >= found.point()):
                found = target
        return found

    def on_close(self, view):
        """The output of the commands of a view that is being closed goes on in a clone of the view."""
        clones = view.clones()
        targets = set(self.targets.values()) | {target for _, target, _ in self.waiting} | {self.current}
        for target in targets:
            if clones and target is not None and target.view == view and target.point() is not None:
                target.move(clones[0], target.point(), target.line() or sublime.Region(target.point()))

    def on_settings_change(self):
        if self.process is not None and process_settings(settings()) != self.snapshot:
            self.stop()
            sublime.status_message('Interactivity: the settings changed, the REPL will restart')

    def _send(self, lines, target, directory=None):
        if self.protocol is None:
            self.waiting.append((lines, target, directory))
            return
        if self.protocol == 'frames':
            self.next_id += 1
            self.targets[self.next_id] = target
            header = json.dumps({'id': self.next_id, 'cwd': directory}, ensure_ascii=False)
            self.writes.put('\x1e{}\n{}\x1e\n'.format(header, ''.join(line + '\n' for line in lines)))
            return
        if lines and lines[-1] != '' and (len(lines) > 1 or ONE_LINE_BLOCK.match(lines[0])):
            # the Python REPL runs a block after an empty line; other REPLs only print another prompt
            lines = lines + ['']
        # without anything to go by, the output belongs to the latest command
        self._set_current(target)
        self._finish_done()
        self.writes.put(''.join(line + '\n' for line in lines))

    def _decide(self, protocol):
        self.protocol = protocol
        waiting, self.waiting = self.waiting, []
        for lines, target, directory in waiting:
            self._send(lines, target, directory)

    def _protocol_timeout(self, generation, greeting):
        # greeting: the number of lines of the greeting when it paused, or None for the timeout of the start
        if generation == self.generation and self.protocol is None and greeting in (None, self.greeting):
            self._decide('lines')

    @staticmethod
    def _write_loop(process, writes):
        while True:
            data = writes.get()
            if data is None:
                break
            try:
                process.stdin.write(data)
                process.stdin.flush()
            except (OSError, ValueError):
                break
        try:
            process.stdin.close()
        except (OSError, ValueError):
            pass

    def _read_loop(self, process, generation, incoming):
        lines, lock = incoming
        try:
            for line in iter(process.stdout.readline, ''):
                with lock:
                    lines.append(line)
                    first = len(lines) == 1
                if first and api_available:
                    sublime.set_timeout(functools.partial(self._deliver, generation), 0)
        except (OSError, ValueError):
            pass
        try:
            process.stdout.close()
        except (OSError, ValueError):
            pass

    def _wait_loop(self, process, generation, reader):
        code = process.wait()
        # the output comes first, unless a process started by the REPL keeps the pipe open
        reader.join(0.5)
        if api_available:
            sublime.set_timeout(functools.partial(self._on_exit, generation, code), 0)

    def _deliver(self, generation):
        if generation != self.generation or self.incoming is None:
            return
        lines, lock = self.incoming
        with lock:
            batch = lines[:]
            del lines[:]
        for line in batch:
            parts = MESSAGE.split(line)
            for i, part in enumerate(parts):
                if i % 2:
                    self._on_message(part)
                elif part:
                    if self.protocol is None and not self.expect_frames:
                        # the greeting of a REPL that doesn't run py_manager.py: the commands go after it
                        self.greeting += 1
                        sublime.set_timeout(functools.partial(self._protocol_timeout, generation, self.greeting),
                                            GREETING_PAUSE)
                    # before the commands, the output goes to the output panel
                    self._emit(part)
        self._flush()

    def _on_message(self, text):
        try:
            message = json.loads(text)
        except ValueError:
            message = None
        if not isinstance(message, dict):
            self._emit('\x1e' + text)
        elif 'interactivity' in message:
            if self.protocol != 'frames':
                self._decide('frames')
        elif 'start' in message:
            # the startup of the REPL is over
            self.suppress = 0
            self.started.add(message['start'])
            self._set_current(self.targets.get(message['start']))
        elif 'done' in message:
            target = self.targets.pop(message['done'], None)
            if target is not None and target is self.current:
                self._set_current(None)
            elif target is not None:
                self.finished.append(target)

    def _emit(self, part):
        if self.suppress > 0:
            self.suppress -= 1
            return
        text = part[:-1] if part.endswith('\n') else part
        if self.batch and self.batch[-1][0] is self.current:
            self.batch[-1][1].append(text)
        else:
            self.batch.append((self.current, [text]))

    def _flush(self):
        batch, self.batch = self.batch, []
        s = settings()
        pattern = s.get('output_filter') or ''
        before = s.get('prepend_output', ' ') or ''
        after = s.get('append_output', '') or ''
        for target, texts in batch:
            if target is None or target.point() is None or target.view.is_read_only():
                # the output of a command is shown when it can't be inserted
                panel_write(''.join(text + '\n' for text in texts), show=target is not None)
                continue
            if pattern:
                try:
                    texts = [re.sub(pattern, '', text) for text in texts]
                except re.error:
                    pass
            target.view.run_command('interactivity_insert_output', {
                'key': target.key, 'text': ''.join('\n' + before + text + after for text in texts)})
        self._finish_done()

    def _set_current(self, target):
        if self.current is not None and self.current is not target:
            self.finished.append(self.current)
        self.current = target

    def _finish_done(self):
        in_use = set(self.targets.values())
        in_use.add(self.current)
        for target in self.finished:
            if target not in in_use:
                target.finish()
        self.finished = [target for target in self.finished if target in in_use]

    def _reset(self):
        """Forgets the commands of the REPL and where their output goes."""
        targets = set(self.targets.values()) | set(self.finished) | {target for _, target, _ in self.waiting}
        targets.add(self.current)
        targets.discard(None)
        for target in targets:
            target.finish()
        self.protocol = None
        self.waiting = []
        self.targets = {}
        self.started = set()
        self.current = None
        self.finished = []
        self.batch = []

    def _on_exit(self, generation, code):
        if generation != self.generation or self.process is None:
            return
        self._deliver(generation)
        not_run = len(self.waiting) + len([key for key in self.targets if key not in self.started])
        self.process = None
        self.writes.put(None)
        self._reset()
        message = 'the REPL exited with code {}'.format(code)
        if not_run:
            message += '; {} command{} didn\'t run'.format(not_run, 's' if not_run > 1 else '')
        report(message, show=bool(not_run) or (code != 0 and time.time() - self.start_time < 5))


class InteractivityListener(sublime_plugin.EventListener):
    def on_text_command(self, view, command_name, args):
        # Enter on lines that start with a text shortcut runs them
        if command_name != 'insert' or not args or args.get('characters') != '\n':
            return None
        if view.settings().get('is_widget') or len(view.sel()) == 0:
            return None
        for region in view.sel():
            line = view.line(region)
            if not region.empty() or shortcut_command(view.substr(line)) is None \
                    or not shortcuts_enabled(view, line.a):
                return None
        return ('interactivity_run_shortcuts', {})

    def on_pre_close(self, view):
        if repl is not None:
            repl.on_close(view)

    def on_exit(self):
        global api_available
        api_available = False
        if repl is not None:
            repl.stop(api=False, wait=True)


class InteractivityCommand(sublime_plugin.TextCommand):
    """Runs the current line, or the selected text, in the REPL."""

    def run(self, edit):
        view = self.view
        jobs, seen = [], set()
        for region in view.sel():
            if region.empty():
                code = view.line(region)
            else:
                begin, end = region.begin(), region.end()
                if view.rowcol(end)[1] == 0:
                    # a selection that ends at the start of a line (Ctrl+L, Shift+Down) does not include that line
                    end -= 1
                if view.rowcol(begin)[0] == view.rowcol(end)[0]:
                    code = sublime.Region(begin, end)
                else:
                    code = view.line(sublime.Region(begin, end))
            if (code.a, code.b) not in seen:
                seen.add((code.a, code.b))
                jobs.append((view.line(code.b).b, REPL_PROMPT.sub('', view.substr(code)).split('\n')))
        run_jobs(view, edit, jobs)


class InteractivityRunShortcutsCommand(sublime_plugin.TextCommand):
    """Runs the text shortcuts on the lines of the carets; Enter on such lines runs this command."""

    def run(self, edit):
        jobs, seen = [], set()
        for region in self.view.sel():
            line = self.view.line(region)
            command = shortcut_command(self.view.substr(line))
            if command is not None and line.b not in seen:
                seen.add(line.b)
                jobs.append((line.b, command.split('\n')))
        if jobs:
            run_jobs(self.view, edit, jobs)
        else:
            self.view.run_command('insert', {'characters': '\n'})


class InteractivityInsertOutputCommand(sublime_plugin.TextCommand):
    def run(self, edit, key, text):
        regions = self.view.get_regions(key)
        if not regions or self.view.is_read_only():
            panel_write(text[1:] + '\n', show=True)
            return
        point = regions[0].b
        size = self.view.insert(edit, point, text)
        self.view.add_regions(key, [sublime.Region(point + size)], '', '', sublime.HIDDEN)
        selection = self.view.sel()
        if len(selection) == 1 and selection[0].empty() and selection[0].b == point + size + 1:
            # keep the caret below the output in sight
            self.view.show(selection[0])


class InteractivityToggleShortcutsCommand(sublime_plugin.TextCommand):
    """Turns running text shortcuts on Enter on or off in this view (tab)."""

    def run(self, edit):
        selection = self.view.sel()
        enabled = not shortcuts_enabled(self.view, self.view.line(selection[0]).a if len(selection) else 0)
        self.view.settings().set('interactivity_shortcuts', enabled)
        sublime.status_message('Interactivity: text shortcuts are {} in this tab'.format('on' if enabled else 'off'))


class InteractivityRestartCommand(sublime_plugin.WindowCommand):
    def run(self):
        view = self.window.active_view()
        if repl.start(directory_of(view) if view else None):
            sublime.status_message('Interactivity: the REPL was restarted')


class InteractivityShowOutputCommand(sublime_plugin.WindowCommand):
    """Shows the messages of the plugin and the output that doesn't belong to a command."""

    def run(self):
        show_panel(self.window)


def plugin_loaded() -> None:
    global repl
    repl = Repl()
    settings().add_on_change(PANEL_NAME, lambda: repl.on_settings_change())


def plugin_unloaded() -> None:
    settings().clear_on_change(PANEL_NAME)
    if repl is not None:
        repl.stop()
