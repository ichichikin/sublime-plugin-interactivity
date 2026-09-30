"""Tests of Interactivity.py with a fake Sublime Text API and real REPL processes."""

import importlib.util
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_sublime as fake  # noqa: E402

fake.install()

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def package_settings():
    with open(os.path.join(PLUGIN_DIR, 'Interactivity.sublime-settings'), encoding='utf-8') as f:
        return json.loads(re.sub(r'^\s*//.*$', '', f.read(), flags=re.MULTILINE))


def load_plugin():
    spec = importlib.util.spec_from_file_location('Interactivity', os.path.join(PLUGIN_DIR, 'Interactivity.py'))
    plugin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plugin)
    return plugin


class PluginTest(unittest.TestCase):
    """Runs the plugin with the settings of the package, and the Python that runs the tests as the REPL."""

    settings = {}

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        fake.reset(self.folder)
        values = package_settings()
        values['shell'] = sys.executable
        values.update(self.settings)
        fake.load_settings('Interactivity.sublime-settings').values.update(values)
        self.plugin = load_plugin()
        self.plugin.plugin_loaded()
        self.window = fake.Window([self.folder])

    def tearDown(self):
        process = self.plugin.repl.process
        self.plugin.plugin_unloaded()
        if process is not None:
            process.wait(10)
        shutil.rmtree(self.folder, ignore_errors=True)

    def type_line(self, view, text):
        """Adds a line at the end of the view, and presses Enter at its end."""
        view.run_command('append', {'characters': text})
        view.sel().clear()
        view.sel().add(view.size())
        fake.press_enter(view)

    def wait_for(self, get, expected, timeout=15):
        try:
            fake.pump(lambda: get() == expected, timeout)
        except AssertionError:
            pass
        self.assertEqual(get(), expected)

    def panel_log(self):
        return ''.join(self.plugin.panel_log)

    def wait_for_log(self, text, timeout=15):
        try:
            fake.pump(lambda: text in self.panel_log(), timeout)
        except AssertionError:
            pass
        self.assertIn(text, self.panel_log())


class TestShortcuts(PluginTest):
    def test_output_goes_below_the_line(self):
        view = self.window.new_file()
        self.type_line(view, '@1+1')
        self.wait_for(lambda: view.text, '@1+1\n 2\n')
        self.assertEqual(view.carets(), [(8, 8)])

    def test_output_goes_below_the_line_from_the_middle_of_it(self):
        view = self.window.new_file('@1+1')
        view.sel().clear()
        view.sel().add(2)
        fake.press_enter(view)
        self.wait_for(lambda: view.text, '@1+1\n 2\n')

    def test_output_goes_to_its_own_command(self):
        slow, quick = self.window.new_file(), self.window.new_file()
        self.type_line(slow, "@import time; time.sleep(1); print('slow')")
        self.type_line(quick, '@1+1')
        self.wait_for(lambda: (slow.text, quick.text), ("@import time; time.sleep(1); print('slow')\n slow\n", '@1+1\n 2\n'))

    def test_typing_while_a_command_runs(self):
        view = self.window.new_file()
        self.type_line(view, "@import time; time.sleep(0.5); print('late')")
        view.run_command('insert', {'characters': 'abc'})
        self.wait_for(lambda: view.text, "@import time; time.sleep(0.5); print('late')\n late\nabc")
        self.assertEqual(view.carets(), [(len(view.text), len(view.text))])

    def test_running_a_line_again_while_it_runs(self):
        view = self.window.new_file()
        line = "@import time; time.sleep(0.5); n = globals().get('n', 0) + 1; print(n)"
        self.type_line(view, line)
        view.sel().clear()
        view.sel().add(len(line))
        fake.press_enter(view)
        # the output comes in the order of the runs, below the output the line has so far
        self.wait_for(lambda: view.text, line + '\n 1\n 2\n')
        self.assertEqual(view.carets(), [(len(view.text), len(view.text))])

    def test_running_a_line_again_while_its_output_comes(self):
        view = self.window.new_file()
        line = "@import time; print('a'); time.sleep(1); print('b')"
        self.type_line(view, line)
        self.wait_for(lambda: view.text, line + '\n a\n')
        view.sel().clear()
        view.sel().add(len(line))
        fake.press_enter(view)
        self.wait_for(lambda: view.text, line + '\n a\n b\n a\n b\n')

    def test_running_a_line_again_when_it_is_done(self):
        # the new output goes right below the line, as the first one did
        view = self.window.new_file()
        self.type_line(view, "@n = globals().get('n', 0) + 1; print(n)")
        self.wait_for(lambda: view.text, "@n = globals().get('n', 0) + 1; print(n)\n 1\n")
        view.sel().clear()
        view.sel().add(view.line(0).b)
        fake.press_enter(view)
        self.wait_for(lambda: view.text, "@n = globals().get('n', 0) + 1; print(n)\n 2\n\n 1\n")

    def test_several_carets(self):
        view = self.window.new_file('@1+1\n@2+2')
        view.sel().clear()
        view.sel().add(4)
        view.sel().add(9)
        fake.press_enter(view)
        # every caret goes to a new line below its command
        self.wait_for(lambda: view.text, '@1+1\n 2\n\n@2+2\n 4\n')
        self.assertEqual(view.carets(), [(8, 8), (17, 17)])

    def test_a_caret_on_another_line_makes_enter_a_line_break(self):
        view = self.window.new_file('@1+1\ntext')
        view.sel().clear()
        view.sel().add(4)
        view.sel().add(9)
        fake.press_enter(view)
        self.assertEqual(view.text, '@1+1\n\ntext\n')
        self.assertIsNone(self.plugin.repl.process)

    def test_selected_text_makes_enter_a_line_break(self):
        view = self.window.new_file('@1+1')
        view.sel().clear()
        view.sel().add(fake.Region(1, 4))
        self.assertIsNone(self.plugin.InteractivityListener().on_text_command(view, 'insert', {'characters': '\n'}))

    def test_widgets_are_left_alone(self):
        view = self.window.new_file('@1+1')
        view.settings().set('is_widget', True)
        self.assertIsNone(self.plugin.InteractivityListener().on_text_command(view, 'insert', {'characters': '\n'}))

    def test_quotes_and_backslashes_in_a_string_parameter(self):
        fake.load_settings('Interactivity.sublime-settings').set('text_shortcuts', {'@@': 'print(##param_str##)'})
        view = self.window.new_file()
        self.type_line(view, '@@say "hi" \'there\' \\ """ and ##param##')
        self.wait_for(lambda: view.text, '@@say "hi" \'there\' \\ """ and ##param##\n say "hi" \'there\' \\ """ and ##param##\n')

    def test_a_lone_shortcut_ends_a_block_typed_line_by_line(self):
        view = self.window.new_file()
        self.type_line(view, '@for i in range(2):')
        self.type_line(view, '@    print(i)')
        self.type_line(view, '@')
        self.wait_for(lambda: view.text, '@for i in range(2):\n@    print(i)\n@\n 0\n 1\n')

    def test_a_block_in_one_line(self):
        view = self.window.new_file()
        self.type_line(view, '@for i in range(2): print(i)')
        self.type_line(view, '@1+1')
        self.wait_for(lambda: view.text, '@for i in range(2): print(i)\n 0\n 1\n@1+1\n 2\n')

    def test_input_gets_the_next_command(self):
        view = self.window.new_file()
        self.type_line(view, "@name = input('Name? ')")
        self.wait_for(lambda: view.text, "@name = input('Name? ')\n Name?\n")
        self.type_line(view, '@Alice')
        self.type_line(view, '@print(name)')
        self.wait_for(lambda: view.text, "@name = input('Name? ')\n Name?\n@Alice\n@print(name)\n Alice\n")

    def test_commands_run_in_the_folder_of_the_file(self):
        folder = os.path.join(self.folder, 'notes \u00e9')
        os.mkdir(folder)
        with open(os.path.join(folder, 'data.txt'), 'w') as f:
            f.write('next to the note')
        view = self.window.new_file(file_name=os.path.join(folder, 'note.txt'))
        self.type_line(view, "@open('data.txt').read()")
        self.wait_for(lambda: view.text, "@open('data.txt').read()\n 'next to the note'\n")


class TestWhereShortcutsRun(PluginTest):
    def enter(self, view):
        view.sel().clear()
        view.sel().add(view.size())
        fake.press_enter(view)

    def test_source_code_is_left_alone(self):
        view = self.window.new_file('@decorator', scope='source.python')
        self.enter(view)
        self.assertEqual(view.text, '@decorator\n')
        self.assertIsNone(self.plugin.repl.process)

    def test_code_blocks_in_markdown_are_left_alone(self):
        view = self.window.new_file('@decorator', scope='text.html.markdown markup.raw.code-fence source.python')
        self.enter(view)
        self.assertEqual(view.text, '@decorator\n')

    def test_markdown_and_plain_code_fences(self):
        for scope in ('text.html.markdown meta.paragraph', 'text.html.markdown markup.raw.code-fence',
                      'text.restructuredtext', 'text.plain'):
            view = self.window.new_file('@1+1', scope=scope)
            self.enter(view)
            self.wait_for(lambda: view.text, '@1+1\n 2\n')

    def test_toggle_in_this_tab(self):
        view = self.window.new_file('@1+1', scope='source.python')
        view.run_command('interactivity_toggle_shortcuts')
        self.assertIn('Interactivity: text shortcuts are on in this tab', fake.status_messages)
        self.enter(view)
        self.wait_for(lambda: view.text, '@1+1\n 2\n')
        view.run_command('interactivity_toggle_shortcuts')
        self.assertIn('Interactivity: text shortcuts are off in this tab', fake.status_messages)

    def test_everywhere(self):
        fake.load_settings('Interactivity.sublime-settings').set('enabled_selector', '')
        view = self.window.new_file('@1+1', scope='source.python')
        self.enter(view)
        self.wait_for(lambda: view.text, '@1+1\n 2\n')


class TestRunCommand(PluginTest):
    def test_a_selection_of_whole_lines(self):
        # Ctrl+L selects a line with its line break: the next line is not a part of it
        view = self.window.new_file('x = 5\nThis is prose\n')
        view.sel().clear()
        view.sel().add(fake.Region(0, 6))
        view.run_command('interactivity')
        self.type_line(view, '@x')
        self.wait_for(lambda: view.text, 'x = 5\n\nThis is prose\n@x\n 5\n')

    def test_a_selected_block(self):
        view = self.window.new_file('def f(x):\n    return x * 2')
        view.sel().clear()
        view.sel().add(fake.Region(0, view.size()))
        view.run_command('interactivity')
        self.type_line(view, '@f(2)')
        self.wait_for(lambda: view.text, 'def f(x):\n    return x * 2\n@f(2)\n 4\n')

    def test_lines_copied_from_a_python_console(self):
        view = self.window.new_file('>>> a = 2\n>>> for i in range(2):\n...     a += 1\n...\n>>> a * 3')
        view.sel().clear()
        view.sel().add(fake.Region(0, view.size()))
        view.run_command('interactivity')
        self.wait_for(lambda: view.text, '>>> a = 2\n>>> for i in range(2):\n...     a += 1\n...\n>>> a * 3\n 12\n')

    def test_two_carets_on_one_line_run_it_once(self):
        view = self.window.new_file('print(1)')
        view.sel().clear()
        view.sel().add(1)
        view.sel().add(3)
        view.run_command('interactivity')
        self.wait_for(lambda: view.text, 'print(1)\n 1\n')


class TestOutput(PluginTest):
    def test_read_only_view(self):
        view = self.window.new_file()
        self.type_line(view, "@import time; time.sleep(0.5); print('late')")
        view.set_read_only(True)
        self.wait_for_log('late\n')
        self.assertEqual(view.text, "@import time; time.sleep(0.5); print('late')\n")
        self.assertEqual(self.window.active_panel(), 'output.interactivity')
        self.assertIn('late\n', self.window.panel_text())

    def test_closed_view(self):
        view = self.window.new_file()
        self.type_line(view, "@import time; time.sleep(0.5); print('late')")
        view.close()
        self.wait_for_log('late\n')
        self.assertEqual(self.window.active_panel(), 'output.interactivity')

    def test_clone_of_a_closed_view(self):
        view = self.window.new_file()
        self.type_line(view, "@import time; time.sleep(0.5); print('late')")
        clone = view.clone()
        view.close()
        self.wait_for(lambda: clone.text, "@import time; time.sleep(0.5); print('late')\n late\n")
        self.assertIsNone(self.window.active_panel())

    def test_prepend_append_and_filter(self):
        fake.load_settings('Interactivity.sublime-settings').update(
            {'prepend_output': '> ', 'append_output': ' <', 'output_filter': '^x'})
        view = self.window.new_file()
        self.type_line(view, "@print('xab')")
        self.wait_for(lambda: view.text, "@print('xab')\n> ab <\n")

    def test_no_filter_by_default(self):
        view = self.window.new_file()
        self.type_line(view, "@print('... loading'); print('>>> 1 + 1')")
        self.wait_for(lambda: view.text, "@print('... loading'); print('>>> 1 + 1')\n ... loading\n >>> 1 + 1\n")

    def test_invalid_filter_is_ignored(self):
        fake.load_settings('Interactivity.sublime-settings').set('output_filter', '(')
        view = self.window.new_file()
        self.type_line(view, "@print('(ab')")
        self.wait_for(lambda: view.text, "@print('(ab')\n (ab\n")

    def test_output_that_is_not_utf8(self):
        view = self.window.new_file()
        self.type_line(view, "@import sys; sys.stdout.buffer.write(b'caf\\xe9\\n'); sys.stdout.flush()")
        self.wait_for(lambda: view.text.split('\n')[1], ' caf\ufffd')

    def test_output_without_a_command_goes_to_the_panel(self):
        fake.load_settings('Interactivity.sublime-settings').set('startup_commands', "print('started')")
        view = self.window.new_file()
        self.type_line(view, '@1+1')
        self.wait_for(lambda: view.text, '@1+1\n 2\n')
        self.wait_for_log('started\n')
        self.assertIsNone(self.window.active_panel())

    def test_panel_in_any_window(self):
        fake.load_settings('Interactivity.sublime-settings').set('startup_commands', "print('started')")
        view = self.window.new_file()
        self.type_line(view, '@1+1')
        self.wait_for_log('started\n')
        other = fake.Window()
        other.run_command('interactivity_show_output')
        self.assertEqual(other.active_panel(), 'output.interactivity')
        self.assertIn('started\n', other.panel_text())


class TestProcess(PluginTest):
    def test_exit_and_restart(self):
        view = self.window.new_file()
        self.type_line(view, '@exit(3)')
        self.wait_for_log('Interactivity: the REPL exited with code 3\n')
        self.type_line(view, '@1+1')
        self.wait_for(lambda: view.text, '@exit(3)\n@1+1\n 2\n')
        self.assertIn('Interactivity: the REPL was restarted', fake.status_messages)

    def test_commands_that_did_not_run(self):
        view = self.window.new_file()
        self.type_line(view, '@import time; time.sleep(0.5); exit()')
        self.type_line(view, '@1+1')
        self.type_line(view, '@2+2')
        self.wait_for_log("Interactivity: the REPL exited with code 0; 2 commands didn't run\n")
        self.assertEqual(self.window.active_panel(), 'output.interactivity')

    def test_shell_that_does_not_exist(self):
        fake.load_settings('Interactivity.sublime-settings').set('shell', 'no-such-program-for-interactivity')
        view = self.window.new_file()
        self.type_line(view, '@1+1')
        self.assertIn('cannot start "no-such-program-for-interactivity', self.panel_log())
        self.assertEqual(self.window.active_panel(), 'output.interactivity')
        self.assertEqual(view.text, '@1+1\n')
        self.assertIsNone(self.plugin.repl.process)

    def test_settings_of_the_process_restart_it(self):
        view = self.window.new_file()
        self.type_line(view, '@x = 1')
        fake.pump(lambda: self.plugin.repl.protocol == 'frames')
        process = self.plugin.repl.process
        fake.load_settings('Interactivity.sublime-settings').set('prepend_output', '  ')
        self.assertIs(self.plugin.repl.process, process)
        fake.load_settings('Interactivity.sublime-settings').set('startup_commands', 'x = 42')
        self.assertIsNone(self.plugin.repl.process)
        process.wait(10)
        self.type_line(view, '@x')
        self.wait_for(lambda: view.text, '@x = 1\n@x\n  42\n')

    def test_exit_of_sublime_text_ends_a_busy_repl(self):
        view = self.window.new_file()
        self.type_line(view, '@import time; time.sleep(60)')
        fake.pump(lambda: 1 in self.plugin.repl.started)
        process = self.plugin.repl.process
        start = time.time()
        self.plugin.InteractivityListener().on_exit()
        self.assertIsNotNone(process.poll())
        self.assertLess(time.time() - start, 5)

    def test_unloading_ends_a_busy_repl(self):
        view = self.window.new_file()
        self.type_line(view, '@import time; time.sleep(60)')
        fake.pump(lambda: 1 in self.plugin.repl.started)
        process = self.plugin.repl.process
        start = time.time()
        self.plugin.plugin_unloaded()
        process.wait(10)
        self.assertLess(time.time() - start, 5)


# Python that takes long to start (e.g. while an antivirus checks it), then runs py_manager.py
SLOW_START = '''
import os, runpy, sys, time
time.sleep(2.5)
manager = sys.argv[1]
sys.argv = [manager]
sys.path.insert(0, os.path.dirname(manager))
runpy.run_path(manager, run_name='__main__')
'''


class TestStartup(PluginTest):
    def test_commands_wait_for_py_manager(self):
        script = os.path.join(self.folder, 'slow_start.py')
        with open(script, 'w') as f:
            f.write(SLOW_START)
        fake.load_settings('Interactivity.sublime-settings').set(
            'shell_params', [script, self.plugin.PLUGIN_DIR + 'modules/py_manager.py'])
        view = self.window.new_file('def f(x):\n    return x * 2\nf(3)')
        view.sel().clear()
        view.sel().add(fake.Region(0, view.size()))
        view.run_command('interactivity')
        self.wait_for(lambda: view.text, 'def f(x):\n    return x * 2\nf(3)\n 6\n', timeout=30)
        self.assertEqual(self.plugin.repl.protocol, 'frames')


# a REPL without py_manager.py: greets, then prints every line it gets in upper case
ECHO_REPL = '''
import sys
print('greeting 1')
print('greeting 2')
sys.stdout.flush()
for line in sys.stdin:
    print(line.rstrip('\\n').upper())
    sys.stdout.flush()
'''


class TestOtherRepls(PluginTest):
    def setUp(self):
        super().setUp()
        script = os.path.join(self.folder, 'echo_repl.py')
        with open(script, 'w') as f:
            f.write(ECHO_REPL)
        fake.load_settings('Interactivity.sublime-settings').update(
            {'shell_params': ['-u', script], 'shutdown_commands': '', 'lines_to_suppress': 2})

    def test_greeting_goes_to_the_panel(self):
        fake.load_settings('Interactivity.sublime-settings').set('lines_to_suppress', 0)
        view = self.window.new_file()
        self.type_line(view, '@hello')
        self.wait_for(lambda: view.text, '@hello\n HELLO\n')
        self.assertIn('greeting 1\ngreeting 2\n', self.panel_log())

    def test_output_goes_to_the_latest_command(self):
        view = self.window.new_file()
        self.type_line(view, '@hello')
        self.wait_for(lambda: view.text, '@hello\n HELLO\n')
        self.assertEqual(self.plugin.repl.protocol, 'lines')
        self.type_line(view, '@again')
        self.wait_for(lambda: view.text, '@hello\n HELLO\n@again\n AGAIN\n')

    def test_a_block_gets_an_empty_line(self):
        view = self.window.new_file('first\nsecond')
        view.sel().clear()
        view.sel().add(fake.Region(0, view.size()))
        view.run_command('interactivity')
        self.wait_for(lambda: view.text, 'first\nsecond\n FIRST\n SECOND\n \n')


@unittest.skipIf(os.name == 'nt', 'POSIX command lines')
class TestCommandLine(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        fake.reset(self.folder)
        self.plugin = load_plugin()

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def program(self, name):
        path = os.path.join(self.folder, name)
        with open(path, 'w') as f:
            f.write('#!/bin/sh\n')
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        return path

    def command_line(self, **settings):
        values = package_settings()
        values.update(settings)
        return self.plugin.command_line(fake.Settings(values), {'PATH': self.folder, 'HOME': '/home/me'})

    def test_python_3_comes_first(self):
        self.program('python')
        python3 = self.program('python3')
        self.assertEqual(self.command_line(), [python3, '-qi', self.plugin.PLUGIN_DIR + 'modules/py_manager.py'])

    def test_path_of_the_settings(self):
        mine = self.program('my-python')
        self.assertEqual(self.command_line(shell='my-python', shell_params=['$HOME/x', '${HOME}/y', '$NOPE']),
                         [mine, '/home/me/x', '/home/me/y', '$NOPE'])

    def test_a_command_line_in_the_shell_setting(self):
        self.assertEqual(self.command_line(shell='python3 -i x.py', shell_params=['-q']),
                         ['/bin/sh', '-c', 'python3 -i x.py'])

    def test_a_program_that_does_not_exist(self):
        self.assertEqual(self.command_line(shell='no-such-program', shell_params=['-q']), ['no-such-program', '-q'])


class TestSettings(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        fake.reset(self.folder)
        self.plugin = load_plugin()

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_environment(self):
        env = self.plugin.environment(fake.Settings({
            'environment_variables': {'A': 'new', 'B': '##plugin##x'},
            'enviroment_variables': {'A': 'old spelling'}}))
        self.assertEqual(env['A'], 'old spelling')
        self.assertEqual(env['B'], self.plugin.PLUGIN_DIR + 'x')
        self.assertIn('PYTHONIOENCODING', env)
        self.assertEqual(env['INTERACTIVITY_USER_MODULES'], os.path.join(self.folder, 'User', 'Interactivity'))
        # null removes a variable
        with mock.patch.dict(os.environ, {'INTERACTIVITY_TEST_VARIABLE': 'x'}):
            env = self.plugin.environment(fake.Settings({'environment_variables': {'INTERACTIVITY_TEST_VARIABLE': None}}))
        self.assertNotIn('INTERACTIVITY_TEST_VARIABLE', env)

    def test_shortcuts(self):
        fake.load_settings('Interactivity.sublime-settings').set('text_shortcuts', {
            '@': '##param##', '@@': 'chat(##param_str##)', '!': 'run(##param_str##, ##param##)'})
        self.assertEqual(self.plugin.shortcut_command('@1+1'), '1+1')
        self.assertEqual(self.plugin.shortcut_command('@@caf\u00e9 "x"'), 'chat("caf\u00e9 \\"x\\"")')
        self.assertEqual(self.plugin.shortcut_command('!##param##'), 'run("##param##", ##param##)')
        self.assertEqual(self.plugin.shortcut_command('@'), '')
        self.assertIsNone(self.plugin.shortcut_command('text'))
        # the string literal of older versions breaks on quotes and backslashes
        fake.load_settings('Interactivity.sublime-settings').set('text_shortcuts', {'@@': 'chat4(r"""##param## """)'})
        self.assertEqual(self.plugin.shortcut_command('@@say """hi""" \\'), 'chat4("say \\"\\"\\"hi\\"\\"\\" \\\\")')

    def test_default_selector_matches_the_settings_file(self):
        self.assertEqual(self.plugin.DEFAULT_SELECTOR, package_settings()['enabled_selector'])


if __name__ == '__main__':
    unittest.main()
