# This file is a part of Interactivity plugin

import logging
import os
import sys
import time  # noqa: F401 (available in the REPL)
import types

debug_info = False
all_package_functions_to_globals = True
available_objects = []


# prints formatted line
def log(msg, *args, **kwargs) -> None:
    if isinstance(msg, str):
        msg = msg.replace('\r', '').split('\n')
        for i, m in enumerate(msg[1:]):
            msg[i + 1] = ' >> ' + m
        msg = '\n'.join(msg)
    logging.getLogger().info(msg, *args, **kwargs)


# prints out general information about this script
def info() -> None:
    global available_objects
    log('Python ' + sys.version)
    log('Available objects:' + "".join(['\n' + x for x in available_objects]))


# Runs the commands of the plugin until it closes the input.
#
# The plugin sends every command in a frame: a line with MARK and a JSON header ({"id": 1, "cwd": "folder"}),
# the lines of the command, and a line with MARK alone. The replies are lines with MARK and JSON as well:
# {"interactivity": 1} when the commands can be sent in frames, and {"start": id} and {"done": id} around
# the output of each command. A line outside of a frame is a command of its own, without replies.
#
# The function keeps its own references to the modules it needs, so that the commands can't break it
# by changing global names.
def __interactivity_main(namespace, os=os, sys=sys, logging=logging, types=types) -> None:
    import ast
    import atexit
    import builtins
    import code
    import getpass
    import importlib.machinery
    import importlib.util
    import io
    import json
    import traceback

    mark = '\x1e'
    output = sys.stdout
    # The commands come on a copy of the input of the REPL, and the input itself is emptied: the programs that
    # the commands start (e.g. with subprocess) can't read the commands that follow.
    try:
        commands = open(os.dup(sys.stdin.fileno()), encoding='utf-8', errors='replace')
    except (AttributeError, OSError, ValueError):
        commands = sys.stdin
    else:
        try:
            empty = os.open(os.devnull, os.O_RDONLY)
            os.dup2(empty, sys.stdin.fileno())
            os.close(empty)
        except OSError:
            pass
    # the lines of input that weren't read yet
    answers = []

    def send(**message):
        output.write(mark + json.dumps(message) + '\n')
        output.flush()

    def flush():
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
            except Exception:
                pass

    # the next command of the plugin as (id, folder, lines), or None when the plugin closed the input
    def read():
        line = commands.readline()
        if not line:
            return None
        if line.startswith(mark):
            try:
                header = json.loads(line[1:])
            except ValueError:
                header = None
            if isinstance(header, dict):
                lines = []
                for line in iter(commands.readline, ''):
                    if line.rstrip('\r\n') == mark:
                        break
                    lines.append(line.rstrip('\r\n'))
                return header.get('id'), header.get('cwd'), lines
        return None, None, [line.rstrip('\r\n')]

    # What a command reads as input is the command that follows it. Makes sure that there are lines to read;
    # False when the plugin closed the input.
    def fetch():
        if not answers:
            command = read()
            if command is None:
                return False
            command_id, _, lines = command
            if command_id is not None:
                # the command is an answer, it has no output of its own
                send(done=command_id)
            answers.extend(lines or [''])
        return True

    def input(prompt=''):
        # on a line of its own: the answer is typed on another line of the document
        prompt = str(prompt).rstrip(' \t')
        if prompt:
            sys.stdout.write(prompt if prompt.endswith('\n') else prompt + '\n')
        flush()
        if not fetch():
            raise EOFError
        return answers.pop(0)

    class Input(io.TextIOBase):
        """sys.stdin of the commands: reading all of it (read(), readlines(), a for loop) reads one answer"""

        encoding = 'utf-8'
        errors = 'replace'

        def readable(self):
            return True

        def readline(self, size=-1):
            return answers.pop(0) + '\n' if fetch() else ''

        def readlines(self, hint=-1):
            lines = [line + '\n' for line in answers] if fetch() else []
            del answers[:]
            return lines

        def read(self, size=-1):
            return ''.join(self.readlines())

        def __iter__(self):
            return iter(self.readlines())

        def close(self):
            # exit() closes sys.stdin
            pass

    console = code.InteractiveConsole(namespace, '<stdin>')

    def run(lines):
        if not console.buffer:
            try:
                tree = ast.parse('\n'.join(lines) + '\n', '<stdin>')
            except (SyntaxError, ValueError, OverflowError):
                tree = None
            if tree is not None:
                # A complete command runs like lines typed in the REPL, one line of statements after another,
                # and the values of expressions are shown. Unlike the REPL, a block doesn't need an empty
                # line after it.
                groups = []
                for statement in tree.body:
                    # (end_lineno is new in Python 3.8)
                    if groups and statement.lineno == getattr(groups[-1][-1], 'end_lineno', groups[-1][-1].lineno):
                        groups[-1].append(statement)
                    else:
                        groups.append([statement])
                for group in groups:
                    try:
                        compiled = console.compile.compiler(ast.Interactive(body=group), '<stdin>', 'single')
                    except (SyntaxError, ValueError, OverflowError):
                        console.showsyntaxerror('<stdin>')
                        continue
                    console.runcode(compiled)
                return
        # an incomplete command (e.g. the first line of a block) or its continuation: line by line, like the REPL
        for line in lines:
            console.push(line)

    def loop():
        folder = None
        while True:
            command = read()
            if command is None:
                return
            command_id, command_folder, lines = command
            if command_folder and command_folder != folder:
                # relative paths start from the folder of the command's file (os.chdir() in a command lasts
                # until a command comes from another folder)
                folder = command_folder
                try:
                    os.chdir(folder)
                except (OSError, ValueError):
                    pass
            if command_id is not None:
                send(start=command_id)
            try:
                run(lines)
            except SystemExit as e:
                # the message of exit('message') is a part of the output of the command
                if e.code is not None and not isinstance(e.code, int):
                    print(e.code)
                raise
            except Exception as e:
                # e.g. MemoryError or RecursionError of the parser: an error of the command, as in the REPL
                traceback.print_exception(type(e), e, None)
            finally:
                del answers[:]
                flush()
                if command_id is not None:
                    send(done=command_id)

    # imports a module of py_modules or of the user's folder; a module that fails to import is reported and skipped
    def load(name, label):
        try:
            # unlike importlib.import_module(), the import statement leaves importlib out of tracebacks
            __import__(name)
            return sys.modules[name]
        except (ImportError, SyntaxError) as e:
            print('{} is not loaded: {}'.format(label, e))
        except SystemExit as e:
            print('{} is not loaded: it called exit({})'.format(label, '' if e.code is None else repr(e.code)))
        except Exception as e:
            print('{} is not loaded: {}'.format(label, str(e) or type(e).__name__))
            traceback.print_exception(type(e), e, e.__traceback__.tb_next)
        return None

    def load_modules():
        modules = []
        try:
            import py_modules
        except Exception as e:
            print('py_modules is not loaded: {}'.format(e))
            return modules
        for name in py_modules.__all__:
            module = load('py_modules.' + name, 'py_modules/' + name)
            if module is not None:
                modules.append((name, module))
        # the user's modules are in a folder that survives updates of the plugin
        folder = os.environ.get('INTERACTIVITY_USER_MODULES')
        if folder and os.path.isdir(folder):
            spec = importlib.machinery.ModuleSpec('interactivity_user', None, is_package=True)
            spec.submodule_search_locations = [folder]
            sys.modules[spec.name] = importlib.util.module_from_spec(spec)
            for name in py_modules._module_names(folder):
                module = load('interactivity_user.' + name, os.path.join(folder, name))
                if module is not None:
                    modules.append((name, module))
        return modules

    # the global names of the modules become names of the REPL
    def export(modules):
        for name, value in list(namespace.items()):
            if isinstance(value, types.FunctionType) and not name.startswith('__'):
                available_objects.append(name)
        for name, module in modules:
            for x in dir(module):
                if x.startswith('__'):
                    continue
                try:
                    v = getattr(module, x)
                except Exception:
                    continue
                if x in namespace and isinstance(namespace[x], type(v)):
                    logger.debug('Objects name conflict: %s', x)
                else:
                    namespace[x] = v
                    available_objects.append(x)

    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(line_buffering=True)
    # everything reaches the plugin through one stream, in the order it was written
    sys.stderr = sys.stdout
    send(interactivity=1)

    logger = logging.getLogger()
    logger.setLevel(logging.INFO if debug_info is False else logging.DEBUG)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter('%(asctime)-8s > %(message)s'))
    # other libraries only show their warnings and errors, unless debug_info is on
    console_handler.addFilter(lambda record: debug_info or record.levelno >= logging.WARNING
                              or record.name in ('root', '__main__')
                              or record.name.startswith(('py_modules', 'interactivity_user')))
    logger.propagate = False
    logger.handlers = []
    logger.addHandler(console_handler)
    namespace['logger'] = logger

    sys.stdin = Input()
    builtins.input = input
    getpass.getpass = lambda prompt='Password: ', stream=None: input(prompt)

    try:
        modules = load_modules()
        # the modules themselves are names of the REPL too
        for name, module in modules:
            namespace.setdefault(name, module)
        if all_package_functions_to_globals:
            export(modules)
        del modules
        loop()
        status = 0
    except SystemExit as e:
        status = e.code if e.code is None or isinstance(e.code, int) else 1
    except BaseException:
        traceback.print_exc()
        status = 1
    flush()
    try:
        atexit._run_exitfuncs()
    except Exception:
        pass
    flush()
    # leaves for good: Python runs with -i and would start its own REPL now
    os._exit(status or 0)


if __name__ == '__main__':
    __interactivity_main(globals())
