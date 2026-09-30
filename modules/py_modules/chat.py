# This file is a part of Interactivity plugin

try:
	import openai
except ModuleNotFoundError as e:
	if e.name != 'openai':
		raise
	raise ImportError("the openai library is required (pip install openai)") from None

import re
import logging


# the Responses API came with openai 1.66.0
__open_ai_min_version = (1, 66)

__open_ai_version = re.match(r'(\d+)\.(\d+)', openai.__version__)
if __open_ai_version is None or tuple(map(int, __open_ai_version.groups())) < __open_ai_min_version:
	raise ImportError("openai {}.{}.0 or newer is required, {} is installed (pip install --upgrade openai)".format(
		*__open_ai_min_version, openai.__version__))


__httpx_logger = logging.getLogger("httpx")
__httpx_logger.setLevel(logging.WARNING)
__chat_messages = []
# the models: fast and cheap for chat(), the most capable for chat_plus()
__model = 'gpt-6-luna'
__reasoning_effort = 'low'
__plus_model = 'gpt-6-sol'


# a message in one line, not too long
def __one_line(text) -> str:
	text = ' '.join(str(text).split())
	return text if len(text) <= 300 else text[:300] + '...'


# the message of an error of the API, the connection or the library
def __error_text(e) -> str:
	body = getattr(e, 'body', None)
	message = body['message'] if isinstance(body, dict) and isinstance(body.get('message'), str) else str(e)
	code = getattr(e, 'status_code', None)
	if not isinstance(e, openai.OpenAIError):
		message = '{}: {}'.format(type(e).__name__, message)
	elif code is not None and not message.startswith('Error code:'):
		message = 'Error code: {} - {}'.format(code, message)
	return __one_line(message)


# the text of an answer (or of a refusal), or None for something that isn't an answer
def __answer_text(response):
	try:
		return ''.join((content.text if content.type == 'output_text' else content.refusal) or ''
			for item in response.output if item.type == 'message'
			for content in item.content if content.type in ('output_text', 'refusal'))
	except (AttributeError, TypeError):
		return None


# sends the query to the most capable model
def chat_plus(prompt: str, system: str = None, save_context: bool = True) -> None:
	chat(prompt, system, save_context, __plus_model)


# the old name of chat_plus()
chat4 = chat_plus


# sends the query to ChatGPT
def chat(prompt: str, system: str = None, save_context: bool = True, model: str = None,
		reasoning_effort: str = None) -> None:
	global __chat_messages

	if model is None:
		model = __model
		reasoning_effort = reasoning_effort or __reasoning_effort
	options = {'reasoning': {'effort': reasoning_effort}} if reasoning_effort else {}
	if system:
		options['instructions'] = system

	try:
		# without openai.api_key the OPENAI_API_KEY environment variable is used
		client = openai.OpenAI(api_key=openai.api_key or None)
	except openai.OpenAIError as e:
		print("Set up the OpenAI API key first: {}\n".format(__error_text(e)))
		return
	except Exception as e:
		print("Unable to use the openai library ({}), try: pip install --upgrade openai\n".format(__error_text(e)))
		return

	history = list(__chat_messages) if save_context else []
	while True:
		try:
			# the conversation is kept here, not on the servers of OpenAI
			response = client.responses.create(
				model=model, input=history + [{"role": "user", "content": prompt}], store=False, **options)
			break
		except openai.BadRequestError as e:
			# the conversation doesn't fit into the context window: forget the oldest exchange and try again
			if getattr(e, 'code', None) == 'context_length_exceeded' and len(history) >= 2:
				del history[:2]
				continue
			print("OpenAI API error: {}\n".format(__error_text(e)))
			return
		except Exception as e:
			print("OpenAI API error: {}\n".format(__error_text(e)))
			return

	answer = __answer_text(response)
	if answer is None:
		print("OpenAI API error: unexpected answer: {}\n".format(__one_line(response)))
		return
	if save_context:
		__chat_messages = history + [
			{"role": "user", "content": prompt},
			{"role": "assistant", "content": answer}
		]
	print(answer + '\n')


# cleans chat history
def clean_chat() -> None:
	global __chat_messages
	__chat_messages = []
