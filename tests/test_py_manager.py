"""Tests of modules/py_manager.py: commands are sent in frames, as the plugin sends them."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANAGER = os.path.join(PLUGIN_DIR, 'modules', 'py_manager.py')
MESSAGE = re.compile('\x1e(\\{[^\\n]*\\})\\n?')


def run(*commands, user_modules=None, cwd=None, manager=MANAGER, pause=None):
    """Runs the commands, each one in a frame, and returns the output of every command (by number, starting
    with 1; None is the output outside of commands), the messages and the exit code of the REPL.
    A command is a list of lines, or a tuple (folder, lines). With a pause (seconds), every command is sent when
    the one before it has started and the pause has passed, as a person types them."""
    env = dict(os.environ, PYTHONIOENCODING='utf-8', INTERACTIVITY_USER_MODULES=user_modules or '')
    env.pop('PYTHONUNBUFFERED', None)
    process = subprocess.Popen([sys.executable, '-qi', manager], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, encoding='utf-8', errors='replace', env=env,
                               cwd=cwd or tempfile.gettempdir())
    received = []
    reader = threading.Thread(target=lambda: received.extend(iter(process.stdout.readline, '')), daemon=True)
    reader.start()
    for number, command in enumerate(commands, 1):
        folder, lines = command if isinstance(command, tuple) else (None, command)
        header = json.dumps({'id': number, 'cwd': folder})
        process.stdin.write('\x1e{}\n{}\x1e\n'.format(header, ''.join(line + '\n' for line in lines)))
        process.stdin.flush()
        if pause is not None:
            deadline = time.time() + 30
            while '\x1e{"start": %d}' % number not in ''.join(received) and time.time() < deadline:
                time.sleep(0.01)
            time.sleep(pause)
    process.stdin.close()
    process.wait(60)
    reader.join(10)
    output = ''.join(received)
    outputs, messages, current = {None: ''}, [], None
    for i, part in enumerate(MESSAGE.split(output)):
        if i % 2:
            message = json.loads(part)
            messages.append(message)
            if 'start' in message:
                current = message['start']
            elif message.get('done') == current:
                current = None
        else:
            outputs[current] = outputs.get(current, '') + part
    return outputs, messages, process.returncode


class TestCommands(unittest.TestCase):
    def test_protocol(self):
        outputs, messages, code = run(['1+1'], ['print("a", end="")'], ['x = 1'])
        self.assertEqual(messages, [{'interactivity': 1}, {'start': 1}, {'done': 1}, {'start': 2}, {'done': 2},
                                    {'start': 3}, {'done': 3}])
        self.assertEqual((outputs[1], outputs[2], outputs.get(3, '')), ('2\n', 'a', ''))
        self.assertEqual(code, 0)

    def test_blocks_need_no_empty_line(self):
        outputs, _, _ = run(['for i in range(2):', '    print(i)', 'print("after")'], ['for i in range(2): print(i)'])
        self.assertEqual(outputs[1], '0\n1\nafter\n')
        self.assertEqual(outputs[2], '0\n1\n')

    def test_a_block_line_by_line(self):
        outputs, _, _ = run(['def f(x):'], ['    return x * 2'], [''], ['f(21)'])
        self.assertEqual(outputs[4], '42\n')

    def test_an_incomplete_command_goes_on_in_the_next_one(self):
        outputs, _, _ = run(['x = (1,'], ['2)'], ['x'])
        self.assertEqual(outputs[3], '(1, 2)\n')

    def test_errors_stop_the_rest_of_their_line_only(self):
        outputs, _, _ = run(['1/0; print("same line")', 'print("next line")'])
        self.assertIn('ZeroDivisionError', outputs[1])
        self.assertNotIn('same line', outputs[1])
        self.assertTrue(outputs[1].endswith('next line\n'))

    def test_output_order(self):
        outputs, _, _ = run(['print("before"); import warnings; warnings.warn("careful")', 'print("after")'])
        self.assertRegex(outputs[1], r'^before\n.*UserWarning: careful\nafter\n$')
        outputs, _, _ = run(['print("before"); 1/0'])
        self.assertTrue(outputs[1].startswith('before\nTraceback'))

    def test_folder_of_a_command(self):
        first, second = tempfile.mkdtemp(suffix=' \u00e9'), tempfile.mkdtemp()
        try:
            here = 'import os; print(os.path.samefile(os.getcwd(), {!r}))'.format
            outputs, _, _ = run((first, [here(first)]), (first, ['os.chdir({!r})'.format(second)]),
                                (first, [here(second)]), (second, [here(second)]), (first, [here(first)]))
            # os.chdir() lasts until a command comes from another folder
            self.assertEqual([outputs[1], outputs[3], outputs[4], outputs[5]], ['True\n'] * 4)
        finally:
            shutil.rmtree(first)
            shutil.rmtree(second)

    def test_errors_of_the_compiler_stop_the_rest_of_their_line_only(self):
        outputs, _, _ = run(['return 1', 'print("next line")'])
        self.assertIn('SyntaxError', outputs[1])
        self.assertTrue(outputs[1].endswith('next line\n'))

    def test_commands_too_big_for_the_parser(self):
        outputs, _, code = run(['x = ' + '-' * 100000 + '1'], ['print("alive")'])
        self.assertIn('MemoryError', outputs[1])
        self.assertEqual(outputs[2], 'alive\n')
        self.assertEqual(code, 0)

    def test_future_imports_are_kept(self):
        outputs, _, _ = run(['from __future__ import annotations'], ['def f(x: NotDefinedAnywhere): return x', 'f(5)'])
        self.assertEqual(outputs[2], '5\n')

    def test_exit(self):
        outputs, messages, code = run(['exit(3)'], ['print("never")'])
        self.assertEqual(code, 3)
        self.assertNotIn({'start': 2}, messages)
        outputs, _, code = run(['exit("bye")'])
        self.assertEqual((outputs[1], code), ('bye\n', 1))

    def test_logging(self):
        outputs, _, _ = run(['import logging', 'logging.getLogger("library").info("hidden")',
                             'logging.getLogger("library").warning("shown")', 'log("mine")', 'logger.info("root")'])
        self.assertNotIn('hidden', outputs[1])
        self.assertRegex(outputs[1], r'> shown\n.*> mine\n.*> root\n')


class TestInput(unittest.TestCase):
    def test_input_gets_the_next_command(self):
        outputs, messages, _ = run(['name = input("Name? ")', 'print("hello", name)'], ['Bob'], ['print(name)'])
        self.assertEqual(outputs[1], 'Name?\nhello Bob\n')
        self.assertEqual(outputs[3], 'Bob\n')
        # the answer has no output of its own
        self.assertNotIn({'start': 2}, messages)
        self.assertLess(messages.index({'done': 2}), messages.index({'done': 1}))

    def test_several_lines_answer_several_questions(self):
        outputs, _, _ = run(['a = input(); b = input(); print(a, b)'], ['first', 'second', 'third'], ['input()'], ['x'])
        self.assertEqual(outputs[1], 'first second\n')
        # the other lines of an answer are dropped when the command ends
        self.assertEqual(outputs[3], "'x'\n")

    def test_getpass_and_stdin(self):
        outputs, _, _ = run(['import getpass, sys; p = getpass.getpass()'], ['secret'],
                            ['print(p[::-1], repr(sys.stdin.readline()))'], ['line'],
                            ['print(repr(sys.stdin.read()))'], ['one', 'two'],
                            ['sys.stdin.close(); print(sys.stdin.closed)'])
        self.assertEqual(outputs[1], 'Password:\n')
        self.assertEqual(outputs[3], "terces 'line\\n'\n")
        self.assertEqual(outputs[5], "'one\\ntwo\\n'\n")
        self.assertEqual(outputs[7], 'False\n')

    def test_reading_all_of_the_input_reads_one_answer(self):
        outputs, _, _ = run(['import sys; lines = sys.stdin.readlines()'], ['a', 'b'],
                            ['for line in sys.stdin: print(line.strip())'], ['c', 'd'], ['print(lines)'])
        self.assertEqual(outputs[3], 'c\nd\n')
        self.assertEqual(outputs[5], "['a\\n', 'b\\n']\n")

    def test_programs_started_by_a_command_get_no_input(self):
        # the next command comes while the program runs, and it isn't the program's input
        outputs, _, _ = run(['import subprocess, sys',
                             'subprocess.call([sys.executable, "-c", "import sys, time; time.sleep(1); '
                             'print(repr(sys.stdin.read()))"])'],
                            ['print("next")'], pause=0.5)
        self.assertEqual(outputs[1], "''\n0\n")
        self.assertEqual(outputs[2], 'next\n')

    def test_help_and_pdb(self):
        outputs, _, _ = run(['help()'], ['q'], ['breakpoint()'], ['p 6 * 7'], ['c'], ['print("in sync")'])
        self.assertIn('help>', outputs[1])
        self.assertIn('42', outputs[3])
        self.assertEqual(outputs[6], 'in sync\n')


class TestModules(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.folder)

    def module(self, name, text):
        path = os.path.join(self.folder, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(textwrap.dedent(text))

    def test_names_of_modules(self):
        self.module('my-mod.py', 'dash_value = "dash"')
        self.module('1st.py', 'first_value = 1')
        self.module('_private.py', 'private_value = "private"')
        self.module('uses_private.py', 'from ._private import private_value as imported_value')
        self.module('pkg/__init__.py', 'package_value = "package"')
        self.module('no_package/inner.py', 'inner_value = "inner"')
        outputs, _, _ = run(['print(dash_value, first_value, imported_value, package_value)'],
                            ["print('private_value' in globals(), 'inner_value' in globals())"],
                            ['print(type(uses_private).__name__)'], user_modules=self.folder)
        self.assertEqual(outputs[1], 'dash 1 private package\n')
        self.assertEqual(outputs[2], 'False False\n')
        self.assertEqual(outputs[3], 'module\n')

    def test_modules_that_fail(self):
        self.module('a_missing.py', 'import no_such_module_anywhere')
        self.module('b_quits.py', 'exit()')
        self.module('c_raises.py', 'raise RuntimeError("boom")')
        self.module('d_fine.py', 'fine_value = 1')
        outputs, _, _ = run(['print(fine_value)'], ['x = input()'], ['answer'], ['print(x)'], user_modules=self.folder)
        startup = outputs[None]
        self.assertIn("a_missing is not loaded: No module named 'no_such_module_anywhere'\n", startup)
        self.assertIn('b_quits is not loaded: it called exit()\n', startup)
        self.assertIn('c_raises is not loaded: boom\n', startup)
        self.assertIn('c_raises.py", line 1', startup)
        self.assertNotIn('importlib', startup)
        self.assertEqual(outputs[1], '1\n')
        # exit() closed sys.stdin, but input() still works
        self.assertEqual(outputs[4], 'answer\n')

    def test_names_of_modules_without_their_global_names(self):
        copy = os.path.join(self.folder, 'modules')
        shutil.copytree(os.path.join(PLUGIN_DIR, 'modules'), copy, ignore=shutil.ignore_patterns('__pycache__'))
        manager = os.path.join(copy, 'py_manager.py')
        with open(manager) as f:
            text = f.read().replace('all_package_functions_to_globals = True', 'all_package_functions_to_globals = False')
        with open(manager, 'w') as f:
            f.write(text)
        self.module('user/mymod.py', 'value = 1')
        outputs, _, _ = run(["print(mymod.value, 'value' in globals())"], manager=manager,
                            user_modules=os.path.join(self.folder, 'user'))
        self.assertEqual(outputs[1], '1 False\n')

    def test_names_that_hide_the_names_of_the_repl(self):
        self.module('clobber.py', '''
            module = 'not a module'
            os = 'not os'
            sys = 'not sys'
            json = 'not json'
        ''')
        outputs, _, _ = run(['print(os, sys)'], (self.folder, ['x = input()']), ['answer'], ['print(x)'],
                            user_modules=self.folder)
        self.assertEqual(outputs[1], 'not os not sys\n')
        self.assertEqual(outputs[4], 'answer\n')


if __name__ == '__main__':
    unittest.main()
