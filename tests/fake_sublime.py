"""A small fake of the sublime and sublime_plugin modules: enough of the API to run Interactivity.py in tests.

install() puts the fake modules into sys.modules. Callbacks of set_timeout() run on the test's thread in pump(),
as they run on the main thread of Sublime Text.
"""

import heapq
import itertools
import os
import re
import sys
import threading
import time
import types

HIDDEN = 128

_ids = itertools.count(1)
_sequence = itertools.count()
_timeouts = []
_lock = threading.Lock()
_settings = {}
_windows = []
status_messages = []
callback_errors = []
packages = None


class Region:
    def __init__(self, a, b=None):
        self.a = a
        self.b = a if b is None else b

    def __eq__(self, other):
        return isinstance(other, Region) and (self.a, self.b) == (other.a, other.b)

    def __repr__(self):
        return 'Region({}, {})'.format(self.a, self.b)

    def begin(self):
        return min(self.a, self.b)

    def end(self):
        return max(self.a, self.b)

    def empty(self):
        return self.a == self.b


class Settings:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.callbacks = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        self.changed()

    def update(self, values):
        """Changes several settings at once, like saving a settings file."""
        self.values.update(values)
        self.changed()

    def add_on_change(self, tag, callback):
        self.callbacks[tag] = callback

    def clear_on_change(self, tag):
        self.callbacks.pop(tag, None)

    def changed(self):
        for callback in list(self.callbacks.values()):
            callback()


def load_settings(name):
    return _settings.setdefault(name, Settings())


def status_message(text):
    status_messages.append(text)


def set_timeout(callback, delay=0):
    with _lock:
        heapq.heappush(_timeouts, (time.monotonic() + delay / 1000.0, next(_sequence), callback))


set_timeout_async = set_timeout


def pump(until=None, timeout=15.0):
    """Runs the callbacks that are due until until() is true (or, without until, until none is due)."""
    deadline = time.monotonic() + timeout
    while True:
        with _lock:
            due = _timeouts and _timeouts[0][0] <= time.monotonic()
            callback = heapq.heappop(_timeouts)[2] if due else None
        if callback is not None:
            try:
                callback()
            except Exception as e:
                callback_errors.append(e)
                raise
            continue
        if until is None or until():
            return
        if time.monotonic() > deadline:
            raise AssertionError('timed out waiting for the plugin')
        time.sleep(0.01)


def packages_path():
    return packages


def version():
    return '4215'


def platform():
    return 'windows' if os.name == 'nt' else 'linux'


class Buffer:
    def __init__(self, text):
        self.text = text
        self.read_only = False
        self.views = []


class Selection:
    def __init__(self):
        self.regions = []

    def __iter__(self):
        return iter(list(self.regions))

    def __len__(self):
        return len(self.regions)

    def __getitem__(self, index):
        return self.regions[index]

    def clear(self):
        self.regions = []

    def add(self, region):
        self.regions.append(region if isinstance(region, Region) else Region(region))
        self.regions.sort(key=lambda region: region.begin())


class View:
    def __init__(self, window, text='', file_name=None, scope='text.plain', buffer=None):
        self.view_id = next(_ids)
        self.window_ = window
        self.buffer = buffer or Buffer(text)
        self.buffer.views.append(self)
        self.file_name_ = file_name
        self.scope = scope
        self.valid = True
        self.regions = {}
        self.selection = Selection()
        self.settings_ = Settings()
        self.shown = []

    def __eq__(self, other):
        return isinstance(other, View) and other.view_id == self.view_id

    def __hash__(self):
        return self.view_id

    def id(self):
        return self.view_id

    def buffer_id(self):
        return id(self.buffer)

    def clones(self):
        return [view for view in self.buffer.views if view is not self]

    def is_valid(self):
        return self.valid

    def is_read_only(self):
        return self.buffer.read_only

    def set_read_only(self, value):
        self.buffer.read_only = value

    def file_name(self):
        return self.file_name_

    def window(self):
        return self.window_ if self.valid else None

    def settings(self):
        return self.settings_

    @property
    def text(self):
        return self.buffer.text

    def size(self):
        return len(self.buffer.text)

    def substr(self, region):
        return self.buffer.text[region.begin():region.end()]

    def line(self, x):
        if isinstance(x, Region):
            return Region(self.line(x.begin()).a, self.line(x.end()).b)
        start = self.buffer.text.rfind('\n', 0, x) + 1
        end = self.buffer.text.find('\n', x)
        return Region(start, len(self.buffer.text) if end < 0 else end)

    def rowcol(self, point):
        return self.buffer.text.count('\n', 0, point), point - (self.buffer.text.rfind('\n', 0, point) + 1)

    def match_selector(self, point, selector):
        return match_selector(self.scope, selector)

    def sel(self):
        return self.selection

    def show(self, location, *args, **kwargs):
        self.shown.append(location)

    def insert(self, edit, point, text):
        if self.buffer.read_only:
            return 0
        self.buffer.text = self.buffer.text[:point] + text + self.buffer.text[point:]
        for view in self.buffer.views:
            view.moved(point, len(text))
        return len(text)

    def moved(self, point, size):
        # like Sublime Text: a region or a caret that starts at the point of an insertion moves after the new text,
        # a region that ends there stays in front of it
        def move(region):
            begin, end = region.begin(), region.end()
            end = end + size if end > point or end == point == begin else end
            begin = begin + size if begin >= point else begin
            return Region(begin, end) if region.a <= region.b else Region(end, begin)

        for key, regions in self.regions.items():
            self.regions[key] = [move(region) for region in regions]
        self.selection.regions = [move(region) for region in self.selection.regions]

    def add_regions(self, key, regions, scope='', icon='', flags=0):
        self.regions[key] = list(regions)

    def get_regions(self, key):
        return list(self.regions.get(key, [])) if self.valid else []

    def erase_regions(self, key):
        self.regions.pop(key, None)

    def run_command(self, name, args=None):
        run_command(self, name, args or {})

    # for tests
    def close(self):
        for listener in listeners():
            if hasattr(listener, 'on_pre_close'):
                listener.on_pre_close(self)
        self.valid = False
        self.buffer.views.remove(self)
        if self in self.window_.views_:
            self.window_.views_.remove(self)

    def clone(self):
        view = View(self.window_, file_name=self.file_name_, scope=self.scope, buffer=self.buffer)
        self.window_.views_.append(view)
        return view

    def carets(self):
        return [(region.a, region.b) for region in self.selection]


class Window:
    def __init__(self, folders=()):
        self.window_id = next(_ids)
        self.views_ = []
        self.folders_ = list(folders)
        self.panels = {}
        self.panel = None
        self.valid = True
        _windows.append(self)

    def __eq__(self, other):
        return isinstance(other, Window) and other.window_id == self.window_id

    def id(self):
        return self.window_id

    def is_valid(self):
        return self.valid

    def views(self, **kwargs):
        return list(self.views_)

    def active_view(self):
        return self.views_[-1] if self.views_ else None

    def folders(self):
        return list(self.folders_)

    def new_file(self, text='', file_name=None, scope='text.plain'):
        view = View(self, text, file_name, scope)
        self.views_.append(view)
        view.sel().add(Region(len(text)))
        return view

    def find_output_panel(self, name):
        return self.panels.get(name)

    def create_output_panel(self, name, unlisted=False):
        if name not in self.panels:
            self.panels[name] = View(self, scope='text.plain')
            self.panels[name].settings().set('is_widget', True)
        return self.panels[name]

    def destroy_output_panel(self, name):
        self.panels.pop(name, None)
        if self.panel == 'output.' + name:
            self.panel = None

    def active_panel(self):
        return self.panel

    def run_command(self, name, args=None):
        run_command(self, name, args or {})

    def panel_text(self, name='interactivity'):
        panel = self.panels.get(name)
        return panel.text if panel else None

    def close(self):
        for view in list(self.views_):
            view.close()
        self.valid = False
        _windows.remove(self)


class NoWindow(Window):
    def __init__(self):
        self.window_id = 0
        self.views_ = []
        self.folders_ = []
        self.panels = {}
        self.panel = None
        self.valid = False


def active_window():
    return _windows[-1] if _windows else NoWindow()


def windows():
    return list(_windows)


def match_selector(scope, selector):
    """A part of Sublime Text's selectors: "a, b - c" (a comma between alternatives, and - for exclusions)."""
    def matches(name):
        return any(atom == name or atom.startswith(name + '.') for atom in scope.split())

    for alternative in selector.split(','):
        names = [name.strip() for name in alternative.split(' - ')]
        if names[0] and matches(names[0]) and not any(matches(name) for name in names[1:]):
            return True
    return False


# sublime_plugin

_commands = {}
_listeners = []


def command_name(cls):
    name = cls.__name__[:-len('Command')] if cls.__name__.endswith('Command') else cls.__name__
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', name).lower()


class EventListener:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        _listeners[:] = [listener for listener in _listeners if type(listener).__name__ != cls.__name__]
        _listeners.append(cls())


class TextCommand:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        _commands[command_name(cls)] = cls

    def __init__(self, view):
        self.view = view


class WindowCommand:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        _commands[command_name(cls)] = cls

    def __init__(self, window):
        self.window = window


def listeners():
    return list(_listeners)


def run_command(target, name, args):
    if isinstance(target, View):
        if name in ('insert', 'append'):
            text = args.get('characters', '')
            points = [target.size()] if name == 'append' else [region.b for region in target.sel()]
            for point in reversed(points):
                if name == 'append':
                    target.buffer.read_only, read_only = False, target.buffer.read_only
                    target.insert(None, point, text)
                    target.buffer.read_only = read_only
                else:
                    target.insert(None, point, text)
            return
        if name in _commands and issubclass(_commands[name], TextCommand):
            _commands[name](target).run(object(), **args)
            return
    elif isinstance(target, Window):
        if name == 'show_panel':
            target.panel = args['panel']
            return
        if name == 'hide_panel':
            target.panel = None
            return
        if name in _commands and issubclass(_commands[name], WindowCommand):
            _commands[name](target).run(**args)
            return
    raise AssertionError('unknown command {!r}'.format(name))


def press_enter(view):
    """Enter as a key press: the listeners may run another command instead of inserting a line break."""
    for listener in listeners():
        if hasattr(listener, 'on_text_command'):
            replacement = listener.on_text_command(view, 'insert', {'characters': '\n'})
            if replacement:
                view.run_command(*replacement)
                return
    view.run_command('insert', {'characters': '\n'})


def reset(packages_folder):
    global packages
    packages = packages_folder
    with _lock:
        del _timeouts[:]
    _settings.clear()
    del _windows[:]
    del status_messages[:]
    del callback_errors[:]


def install():
    sublime = types.ModuleType('sublime')
    for name in ('HIDDEN', 'Region', 'Settings', 'load_settings', 'status_message', 'set_timeout',
                 'set_timeout_async', 'packages_path', 'version', 'platform', 'active_window', 'windows'):
        setattr(sublime, name, globals()[name])
    sublime_plugin = types.ModuleType('sublime_plugin')
    for name in ('EventListener', 'TextCommand', 'WindowCommand'):
        setattr(sublime_plugin, name, globals()[name])
    sys.modules['sublime'] = sublime
    sys.modules['sublime_plugin'] = sublime_plugin
