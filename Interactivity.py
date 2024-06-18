import sublime
import sublime_plugin
import os
import subprocess
import re
import sys
from threading import Thread
from queue import Queue, Empty

interactivity_subprocess = None
interactivity_thread = None
interactivity_output_queue = Queue()
interactivity_lines_to_suppress = 0
interactivity_shortcuts = {}


class EnterKeyListener(sublime_plugin.EventListener):
    def on_text_command(self, view, command_name, args) -> None:
        global interactivity_subprocess
        if command_name == 'insert' and args and 'characters' in args and args['characters'] == '\n':
            if interactivity_subprocess is not None:
                for region in view.sel():
                    if region.empty():
                        current_line_region = view.line(region)
                        current_line_text = view.substr(current_line_region)
                        for shortcut in interactivity_shortcuts.items():
                            if current_line_text.startswith(shortcut[0]):
                                interactivity_subprocess.stdin.write(shortcut[1].replace('##param##', current_line_text[len(shortcut[0]):]) + '\n')
                                view.sel().clear()
                                view.sel().add(sublime.Region(current_line_region.end()))
                                view.show(current_line_region.end())
                                break


class InteractivityCommand(sublime_plugin.TextCommand):
    def run(self, edit) -> None:
        global interactivity_subprocess
        ending = self.view.line_endings()
        if ending == 'system':
            ending = os.linesep
        elif ending == 'windows':
            ending = '\r\n'
        else:
            ending = '\n'

        reg = None
        if self.view.sel()[0].begin() != self.view.sel()[0].end():
            if self.view.line(self.view.sel()[0].begin()).a != self.view.line(self.view.sel()[0].end()).a:
                reg = sublime.Region(self.view.line(self.view.sel()[0]).a, self.view.line(self.view.sel()[0]).b)
        else:
            reg = sublime.Region(self.view.line(self.view.sel()[0]).b, self.view.line(self.view.sel()[0]).b)

        if reg:
            self.view.sel().clear()
            self.view.sel().add(reg)

        sel = self.view.sel()[0]
        self.view.sel().clear()
        self.view.sel().add(self.view.line(sel).b)
        self.view.insert(edit, self.view.line(sel).b, ending)

        line = self.view.substr(self.view.line(sel) if sel.begin() == sel.end() else sel)
        line = re.sub(r'^>>> ', '', re.sub(r'\n>>> ', '\n', line, re.MULTILINE))

        interactivity_subprocess.stdin.write(line + '\n')


class InsertTextCommand(sublime_plugin.TextCommand):
    def run(self, edit, text) -> None:
        global interactivity_lines_to_suppress

        if interactivity_lines_to_suppress:
            interactivity_lines_to_suppress -= 1
            return

        ending = self.view.line_endings()
        if ending == 'system':
            ending = os.linesep
        elif ending == 'windows':
            ending = '\r\n'
        else:
            ending = '\n'

        settings = sublime.load_settings('Interactivity.sublime-settings')
        prepend = settings.get('prepend_output', ' ')
        append = settings.get('append_output', '')
        filter = settings.get('output_filter', '')
        self.view.insert(edit, self.view.sel()[0].end(), ending.join([prepend + x + append for x in re.split('\r?\n', re.sub(filter, '', text))[:-1]]) + ending)


def plugin_loaded() -> None:
    global interactivity_subprocess, interactivity_thread, interactivity_output_queue, interactivity_lines_to_suppress, interactivity_shortcuts

    def enqueue_output(out, queue) -> None:
        for line in iter(out.readline, ''):
            queue.put(line)
            if line.endswith('\'%kill_routine%\'\n'):
                out.close()
                return
        out.close()

    if interactivity_subprocess is None:
        settings = sublime.load_settings('Interactivity.sublime-settings')
        shell_path = settings.get('shell', 'python')
        shell_path = shell_path.replace('##plugin##', os.path.dirname(os.path.realpath(__file__)) + os.sep)
        startup_commands = settings.get('startup_commands', '')
        interactivity_lines_to_suppress = settings.get('lines_to_suppress', 0)
        shortcuts = settings.get('text_shortcuts', {'@': '##param##'})
        for k, v in shortcuts.items():
            interactivity_shortcuts[k] = v
        interactivity_shortcuts = dict(sorted(interactivity_shortcuts.items(), key=lambda item: -len(item[0])))
        shell_params = settings.get('shell_params', [])
        custom_env = settings.get('enviroment_variables', {})
        env = os.environ.copy()
        for k, v in custom_env.items():
            v = v.replace('##plugin##', os.path.dirname(os.path.realpath(__file__)) + os.sep)
            env[k] = v

        interactivity_subprocess = subprocess.Popen([shell_path] + [x.replace('##plugin##', os.path.dirname(os.path.realpath(__file__)) + os.sep) for x in shell_params],
                                             stdin=subprocess.PIPE,
                                             stdout=subprocess.PIPE,
                                             stderr=subprocess.STDOUT,
                                             universal_newlines=True,
                                             env=env,
                                             bufsize=1,
                                             encoding='utf-8',
                                             shell=True)
        if startup_commands:
            interactivity_subprocess.stdin.write(startup_commands + '\n')
        interactivity_thread = Thread(target=enqueue_output, args=(interactivity_subprocess.stdout, interactivity_output_queue))
        interactivity_thread.start()
        sublime.set_timeout_async(process_output, 0)


def process_output() -> None:
    global interactivity_output_queue
    view = sublime.active_window().active_view()
    while True:
        try:
            line = interactivity_output_queue.get_nowait()
        except Empty:
            break
        else:
            if line.endswith('\'%kill_routine%\'\n'):
                return
            view.run_command('insert_text', {'text': line})
    sublime.set_timeout_async(process_output, 25)


def plugin_unloaded() -> None:
    global interactivity_subprocess, interactivity_thread
    if interactivity_subprocess is not None:
        settings = sublime.load_settings('Interactivity.sublime-settings')
        shutdown_commands = settings.get('shutdown_commands', '')
        if shutdown_commands:
            try:
                interactivity_subprocess.stdin.write(shutdown_commands + '\n')
            except:
                pass
        interactivity_subprocess.stdin.write(f'\'%kill_routine%\'\n')
        interactivity_subprocess.kill()
        interactivity_thread.join()
        interactivity_thread = None
        interactivity_subprocess = None
