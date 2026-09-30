"""Tests of the Python modules of the plugin (chat.py with a fake OpenAI API, tables.py)."""

import contextlib
import http.server
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULES = os.path.join(PLUGIN_DIR, 'modules', 'py_modules')


def load(name):
    spec = importlib.util.spec_from_file_location('test_' + name, os.path.join(MODULES, name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def installed(*names):
    return all(importlib.util.find_spec(name) is not None for name in names)


def printed(function, *args, **kwargs):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        function(*args, **kwargs)
    return output.getvalue()


class TestMissingLibraries(unittest.TestCase):
    def test_missing_library(self):
        for module, library in (('chat', 'openai'), ('tables', 'pandas')):
            with mock.patch.dict(sys.modules, {library: None}):
                with self.assertRaisesRegex(ImportError, r'^the {0} library is required \(pip install {0}\)$'.format(library)):
                    load(module)

    def test_missing_dependency_of_a_library(self):
        folder = tempfile.mkdtemp()
        try:
            os.mkdir(os.path.join(folder, 'openai'))
            with open(os.path.join(folder, 'openai', '__init__.py'), 'w') as f:
                f.write('import no_such_dependency\n')
            with mock.patch.object(sys, 'path', [folder] + sys.path), mock.patch.dict(sys.modules):
                sys.modules.pop('openai', None)
                with self.assertRaisesRegex(ImportError, "no_such_dependency"):
                    load('chat')
        finally:
            shutil.rmtree(folder)


def answer(text, kind='output_text'):
    """A response of the Responses API with a message"""
    content = {'type': kind, kind if kind == 'refusal' else 'text': text, 'annotations': []}
    return {'id': 'resp_1', 'object': 'response', 'created_at': 0, 'status': 'completed', 'model': 'gpt-test',
            'output': [{'type': 'reasoning', 'id': 'rs_1', 'summary': []},
                       {'type': 'message', 'id': 'msg_1', 'status': 'completed', 'role': 'assistant',
                        'content': [content]}]}


class FakeApi(http.server.BaseHTTPRequestHandler):
    """Answers with the queued responses: (status, body, content type), or with "ok" when there are none."""

    responses = []
    requests = []
    keys = []

    def do_POST(self):
        FakeApi.keys.append(self.headers.get('Authorization'))
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        request['path'] = self.path
        FakeApi.requests.append(request)
        status, body, content_type = FakeApi.responses.pop(0) if FakeApi.responses else (200, answer('ok'), None)
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type or 'application/json')
        self.send_header('Content-Length', str(len(data)))
        # the library waits that long before it tries again
        self.send_header('retry-after-ms', '1')
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def texts(request):
    return [message['content'] for message in request['input']]


@unittest.skipUnless(installed('openai'), 'the openai library is not installed')
class TestChat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), FakeApi)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        url = 'http://127.0.0.1:{}/v1'.format(self.server.server_address[1])
        environment = mock.patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test', 'OPENAI_BASE_URL': url})
        environment.start()
        self.addCleanup(environment.stop)
        FakeApi.responses[:] = []
        FakeApi.requests[:] = []
        FakeApi.keys[:] = []
        self.chat = load('chat')

    def test_answer_and_history(self):
        FakeApi.responses[:] = [(200, answer('first answer'), None), (200, answer('second answer'), None)]
        self.assertEqual(printed(self.chat.chat, 'first question'), 'first answer\n\n')
        self.assertEqual(printed(self.chat.chat_plus, 'second question', system='be brief'), 'second answer\n\n')
        first, second = FakeApi.requests
        self.assertEqual((first['path'], first['model'], first['reasoning'], first['store']),
                         ('/v1/responses', 'gpt-6-luna', {'effort': 'low'}, False))
        self.assertEqual((second['model'], second['instructions']), ('gpt-6-sol', 'be brief'))
        self.assertNotIn('reasoning', second)
        self.assertEqual(texts(second), ['first question', 'first answer', 'second question'])
        self.assertEqual([message['role'] for message in second['input']], ['user', 'assistant', 'user'])
        self.chat.clean_chat()
        printed(self.chat.chat, 'third question')
        self.assertEqual(texts(FakeApi.requests[2]), ['third question'])

    def test_old_name_of_chat_plus(self):
        self.assertIs(self.chat.chat4, self.chat.chat_plus)

    def test_model_and_reasoning_effort(self):
        printed(self.chat.chat, 'question', model='another-model')
        printed(self.chat.chat, 'question', model='another-model', reasoning_effort='none')
        printed(self.chat.chat, 'question', reasoning_effort='high')
        self.assertEqual([(r['model'], r.get('reasoning')) for r in FakeApi.requests],
                         [('another-model', None), ('another-model', {'effort': 'none'}), ('gpt-6-luna', {'effort': 'high'})])

    def test_refusal(self):
        FakeApi.responses[:] = [(200, answer('I can not help with that.', 'refusal'), None)]
        self.assertEqual(printed(self.chat.chat, 'question'), 'I can not help with that.\n\n')

    def test_key_of_a_startup_command(self):
        # openai.api_key = '...' in "startup_commands", as in older versions of the plugin
        self.chat.openai.api_key = 'sk-startup'
        self.addCleanup(setattr, self.chat.openai, 'api_key', None)
        printed(self.chat.chat, 'question')
        self.assertEqual(FakeApi.keys, ['Bearer sk-startup'])

    def test_a_long_conversation_loses_its_oldest_messages(self):
        printed(self.chat.chat_plus, 'first question')
        too_long = {'error': {'message': 'too long', 'type': 'invalid_request_error', 'param': 'input',
                              'code': 'context_length_exceeded'}}
        FakeApi.responses[:] = [(400, too_long, None), (200, answer('answer'), None)]
        self.assertEqual(printed(self.chat.chat_plus, 'second question'), 'answer\n\n')
        self.assertEqual(FakeApi.requests[-1]['model'], 'gpt-6-sol')
        self.assertEqual(texts(FakeApi.requests[-1]), ['second question'])

    def test_errors_are_one_line_and_keep_the_history(self):
        printed(self.chat.chat, 'first question')
        page = '<html>\n<head><title>502 Bad Gateway</title></head>\n<body>\n</body>\n</html>\n'
        wrong_key = {'error': {'message': 'Incorrect API key provided', 'type': 'invalid_request_error',
                               'code': 'invalid_api_key'}}
        rate_limit = {'error': {'message': 'Rate limit reached', 'type': 'requests', 'code': 'rate_limit_exceeded'}}
        # the library tries 3 times
        FakeApi.responses[:] = [(502, page, 'text/html')] * 3 + [(429, rate_limit, None)] * 3 + [
            (401, wrong_key, None), (200, {'unexpected': True}, None)]
        self.assertEqual(printed(self.chat.chat, 'second question'),
                         'OpenAI API error: Error code: 502 - <html> <head><title>502 Bad Gateway</title></head> '
                         '<body> </body> </html>\n\n')
        self.assertEqual(printed(self.chat.chat, 'rate limit'),
                         'OpenAI API error: Error code: 429 - Rate limit reached\n\n')
        self.assertEqual(printed(self.chat.chat, 'third question'),
                         'OpenAI API error: Error code: 401 - Incorrect API key provided\n\n')
        self.assertTrue(printed(self.chat.chat, 'fourth question').startswith('OpenAI API error: unexpected answer: '))
        printed(self.chat.chat, 'fifth question')
        self.assertEqual(texts(FakeApi.requests[-1]), ['first question', 'ok', 'fifth question'])

    def test_no_key(self):
        del os.environ['OPENAI_API_KEY']
        self.assertTrue(printed(self.chat.chat, 'question').startswith('Set up the OpenAI API key first: '))
        self.assertEqual(FakeApi.requests, [])

    def test_key_that_is_not_ascii(self):
        os.environ['OPENAI_API_KEY'] = 'sk-caf\u00e9'
        self.assertTrue(printed(self.chat.chat, 'question').startswith('OpenAI API error: UnicodeEncodeError: '))

    def test_library_that_does_not_work(self):
        # e.g. an old openai with a new httpx
        with mock.patch.object(self.chat.openai, 'OpenAI', side_effect=TypeError("unexpected keyword argument 'proxies'")):
            self.assertEqual(printed(self.chat.chat, 'question'),
                             "Unable to use the openai library (TypeError: unexpected keyword argument 'proxies'), "
                             "try: pip install --upgrade openai\n\n")

    def test_old_library(self):
        with mock.patch.object(self.chat.openai, '__version__', '1.65.0'):
            with self.assertRaisesRegex(ImportError, r'openai 1\.66\.0 or newer is required, 1\.65\.0 is installed'):
                load('chat')


@unittest.skipUnless(installed('pandas', 'tabulate'), 'pandas or tabulate is not installed')
class TestTables(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.tables = load('tables')

    def tearDown(self):
        shutil.rmtree(self.folder)

    def test_csv(self):
        path = os.path.join(self.folder, 'data.csv')
        with open(path, 'w') as f:
            f.write('a;b\n1;2\n')
        table = '\n|    |   a |   b |\n|---:|----:|----:|\n|  0 |   1 |   2 |\n\n'
        self.assertEqual(printed(self.tables.csv_table, path, sep=';'), table)
        self.assertEqual(printed(self.tables.csv_table, path, ';'), table)

    @unittest.skipUnless(installed('openpyxl'), 'openpyxl is not installed')
    def test_excel_sheets(self):
        import pandas
        path = os.path.join(self.folder, 'data.xlsx')
        with pandas.ExcelWriter(path) as writer:
            pandas.DataFrame({'a': [1]}).to_excel(writer, sheet_name='one', index=False)
            pandas.DataFrame({'b': [2]}).to_excel(writer, sheet_name='two', index=False)
        self.assertEqual(printed(self.tables.excel_table, path),
                         '\n|    |   a |\n|---:|----:|\n|  0 |   1 |\n\n')
        self.assertEqual(printed(self.tables.excel_table, path, sheet_name=None),
                         '\none:\n\n|    |   a |\n|---:|----:|\n|  0 |   1 |\n\n'
                         '\ntwo:\n\n|    |   b |\n|---:|----:|\n|  0 |   2 |\n\n')

    def test_missing_file(self):
        output = printed(self.tables.csv_table, os.path.join(self.folder, 'missing.csv'))
        self.assertTrue(output.startswith('Unable to load the table: '))
        self.assertIn('missing.csv', output)


if __name__ == '__main__':
    unittest.main()
