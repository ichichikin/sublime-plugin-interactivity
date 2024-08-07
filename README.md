# Interactivity for Sublime Text: run Python, Node.js, Java, Perl, PHP, bash, or any other REPLs

**[Feel free to ask any questions about the plugin on the Sublime Text forum!](https://forum.sublimetext.com/t/interactivity-run-python-node-js-java-perl-php-bash-or-any-other-repls/72775)**

Interactivity lets you run local shell commands and scripts directly within your Sublime Text editor, providing the output alongside your written content. Use your favorite tools like Python, Node.js, Java, Perl, PHP, bash, or any other REPLs.

For example, if you need to quickly calculate a project's budget while taking notes, you can type the numbers and hit Enter in the editor to execute the code in the desired REPL:
```markdown
## Mike's rate is $120. Thus, it will cost us:

@120*8*21*12+8000
249920
```

## Installation

To install the `Interactivity` package via Package Control, follow these steps:

1. **Install Package Control (if you haven't already):**
   - Open Sublime Text.
   - Access the command palette by pressing `Ctrl+Shift+P` (Windows/Linux) or `Cmd+Shift+P` (Mac).
   - Type `Install Package Control` and press `Enter`.

2. **Install the Plugin:**
   - Open the command palette again by pressing `Ctrl+Shift+P` (Windows/Linux) or `Cmd+Shift+P` (Mac).
   - Type `Package Control: Install Package` and press `Enter`.
   - In the package list, type `Interactivity` and select it to install.

## Python Modules Collection

My favorite daily tool is Python, which is why I included several sample Python modules in this plugin.

- **chat.py** Integrates ChatGPT directly with the editor. Remember to [set up an OpenAI API key](#setting-up).
- **tables.py** Imports Excel and CSV tables into the editor.

These modules requires following dependencies: `openai`, `pandas`, `tabulate`.

You can intall them with this command: `pip install openai pandas tabulate`.

Here's a demo of how they work:

<img src="demo.gif" alt="Demo" style="width:700px;"/>

### Available Functions in the Modules within Sublime Text

#### `chat.py`

1. **chat(prompt: str, system: str = None, save_context: bool = True, model: str = 'gpt-3.5-turbo') -> None:**
   - **Parameters:**
     - `prompt` (str): The user query to be sent to ChatGPT.
     - `system` (str, optional): An optional system prompt.
     - `save_context` (bool, optional): Whether to save the chat context for continuity. Default is `True`.
     - `model` (str, optional): The model to be used for the chat. Default is `'gpt-3.5-turbo'`.
   - **Output:** Prints the assistant's response directly in the editor.

2. **chat4(prompt: str, system: str = None, save_context: bool = True) -> None:**
   - **Parameters:**
     - `prompt` (str): The user query to be sent to ChatGPT 4o.
     - `system` (str, optional): An optional system prompt.
     - `save_context` (bool, optional): Whether to save the chat context for continuity. Default is `True`.
   - **Output:** Prints the assistant's response directly in the editor.

3. **clean_chat() -> None:**
   - **Output:** Cleans the chat history by resetting the stored messages. This function does not produce a direct output in the editor.

#### `tables.py`

1. **excel_table(path: str, \*args, \*\*kwargs) -> None:**
   - **Parameters:**
     - `path` (str): The path to the Excel file.
     - `*args`: Optional additional positional arguments to be passed to `pandas.read_excel`.
     - `**kwargs`: Optional additional keyword arguments to be passed to `pandas.read_excel`.
   - **Output:** Reads the Excel file and prints it as a markdown table directly in the editor.

2. **csv_table(path: str, \*args, \*\*kwargs) -> None:**
   - **Parameters:**
     - `path` (str): The path to the CSV file.
     - `*args`: Optional additional positional arguments to be passed to `pandas.read_csv`.
     - `**kwargs`: Optional additional keyword arguments to be passed to `pandas.read_csv`.
   - **Output:** Reads the CSV file and prints it as a markdown table directly in the editor.

### Custom Functions
You can add your custom Python scripts to the `py_modules` directory within the plugin's directory. All global functions and variables in these scripts will be accessible within the editor. You are welcome to contribute new useful scripts in your favorite language.

## Setting Up

Edit the `Interactivity.sublime-settings` file in the plugin directory with your desired configurations. Example settings:

Specify the path to any shell executable. Use `##plugin##` to refer to the plugin's directory.
```
"shell": "python",
```

Define commands to run after starting the shell. Specify your OpenAI API key here for chat.py module.
```
"startup_commands": "openai.api_key = 'sk-'",
```

Define commands to run before closing the shell.
```
"shutdown_commands": "exit()",
```

Specify shell command-line arguments. Use `##plugin##` to refer to the plugin's directory.
```
"shell_params": [
   "-qi",
   "##plugin##modules/py_manager.py"
],
```

Set environment variables. Use `##plugin##` to refer to the plugin's directory.
```
"enviroment_variables": {
   "PYTHONIOENCODING": "utf8"
},
```

Specify the number of initial lines to skip (e.g., shell greetings).
```
"lines_to_suppress": 0,
```

Prepend the output with custom text.
```
"prepend_output": " ",
```

Append the output with custom text.
```
"append_output": "",
```

Apply a RegExp pattern to filter the output.
```
"output_filter": "^(?:(?:>>> )|(?:\\.\\.\\. ))+"
```

Define text shortcuts for running commands. The entry key is the shortcut; the entry vakue is the command to execute. Use `##param##` to include the line after the shortcut in the command.
```
"text_shortcuts": {
   "@": "##param##",
   "@@": "chat4(r\"\"\"##param##\"\"\")"
}
```

Aside from using shortcuts, you can also run shell execution by selecting any part of your text and hitting the [Sublime Text hotkeys](https://www.sublimetext.com/docs/key_bindings.html) bound to the package's `Interactivity` command.

### Understanding the Shortcuts

Define text shortcuts to run specific commands with the `text_shortcuts` setting. The text before '->' is the shortcut; the text after is the command to execute. Use `##param##` to include the line after the shortcut in the command.

#### Example 1

```plaintext
@ -> ##param##
```

- `@`: This is the shortcut you type at the beginning of a line in the editor.
- `##param##`: This includes the text that follows the shortcut on the same line. Essentially, it allows you to insert any text directly into the command.

This setup allows you to directly execute the input text as a command.

#### Example 2

```plaintext
"text_shortcuts": {
   "@@": "chat4(r\"\"\"##param## \"\"\", system=\"Use markdown and emojis.\")"
}
```

- `@@`: This is the shortcut you type at the beginning of a line in the editor.
- `chat4(r\"\"\"##param## \"\"\", system=\"Use markdown and emojis.\")`: This command calls the `chat4` function from `chat.py` with specific parameters.

Let's break down the parameters:
- `r\"\"\"##param## \"\"\"`: This includes the text that follows the shortcut on the same line.
- `system=\"Use markdown and emojis.\"`: This sets the system ptompt for the chat.

By using this shortcut, you can quickly initiate a chat with ChatGPT using predefined settings, making your workflow more efficient.

## Setting up Python integration
You can enhance the functionality by adding custom Python scripts to the `py_modules` directory within the plugin's directory. All global functions and variables in these scripts will be accessible within the editor.

### Installing Python

- **Windows:** Download the installer from [python.org](https://www.python.org/downloads/windows/) and follow the installation instructions. Make sure to add Python to your PATH during the installation.
- **Linux:** Use your package manager to install Python. For example, on Ubuntu: `sudo apt-get install python3`.
- **macOS:** Install Python using Homebrew: `brew install python3`.

### Finding Python Executable Path

To find the Python executable path, run the following command in your terminal:

```sh
which python3
```

Use the output of this command as the path in the `shell` setting.


When all is set up, you can call Python code from the Sublime Text:

```plaintext
@import numpy as np
@200 % (10 + 365) / np.e
73.57588823428847

@chat('How are you doing?')
I'm doing well, thanks for asking! How about you? What's on your mind today?

@@How are you doing?
I'm doing well, thank you for asking! How about you? How's your day going?
```

## If You Also Use Obsidian

Check out the [Interactivity: Calculations and Scripts for Obsidian](https://github.com/ichichikin/obsidian-plugin-interactivity).

## Contributing

Contributions are welcome! Please submit a pull request or open an issue to discuss any changes.

## License

This project is licensed under the MIT License.
