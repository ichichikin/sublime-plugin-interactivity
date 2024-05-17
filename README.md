# Interactivity Plugin for Sublime Text

Sometimes you need to compute numbers or access data while working with text. It's handy to do this without leaving the [Sublime Text](https://www.sublimetext.com/) editor, using your favorite tools like Python, Perl, Node.js, or others.
For example, if you need to quickly calculate a project's budget while taking notes, you can type the numbers and hit Enter in the editor to execute the code in the desired REPL:
```plaintext
## Mike's rate is $120. Thus, it will cost us:
@120*8*21*12+8000
249920
```

This plugin allows you to run shell commands and scripts directly within the editor, providing their output right alongside your written content, making your workflow more dynamic and interactive.
By default, it supports running JavaScript, but you can also configure it to run any other shell commands.

## Installation

1. **Clone the Repository:**

```bash
git clone https://github.com/yourusername/sublime-interactivity-plugin.git
```

2. **Copy to Sublime Text Packages Directory:**

Copy the cloned repository to your Sublime Text Packages directory. You can find this directory via Preferences > Browse Packages in Sublime Text.

## Usage
### Setting Up

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

Specify shell command-line arguments, one per line. Use `##plugin##` to refer to the plugin's directory.
```
"shell_params": "-qi\n##plugin##modules/py_manager.py",
```

Set environment variables, one per line. Use `##plugin##` to refer to the plugin's directory.
```
"enviroment_variables": "PYTHONIOENCODING=utf8",
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

Define text shortcuts for running commands. The text before '->' is the shortcut; the text after is the command to execute. Use `##param##` to include the line after the shortcut in the command.
```
"text_shortcuts": "@ -> ##param##\n@@ -> chat4(r\"\"\"##param## \"\"\")",
```

#### Understanding the Shortcuts

Define text shortcuts to run specific commands with the `text_shortcuts` setting. The text before '->' is the shortcut; the text after is the command to execute. Use `##param##` to include the line after the shortcut in the command.

##### Example 1

```plaintext
@ -> ##param##
```

- `@`: This is the shortcut you type at the beginning of a line in the editor.
- `##param##`: This includes the text that follows the shortcut on the same line. Essentially, it allows you to insert any text directly into the command.

This setup allows you to directly execute the input text as a command.

##### Example 2

```plaintext
@@ -> chat4(r"""##param## """, system='Use markdown and emojis.')
```

- `@@`: This is the shortcut you type at the beginning of a line in the editor.
- `chat4(r"""##param## """, system='Use markdown and emojis.')`: This command calls the `chat` function from `chat.py` with specific parameters.

Let's break down the parameters:
- `r"""##param## """`: This includes the text that follows the shortcut on the same line.
- `system='Use markdown and emojis.'`: This sets the system ptompt for the chat.

By using this shortcut, you can quickly initiate a chat with ChatGPT using predefined settings, making your workflow more efficient.

##### Iterating Shortcuts

You can iterate both shortcuts by dividing them with a new line in the editor:

```plaintext
@ -> ##param##\n@@ -> chat4(r"""##param## """, system='Use markdown and emojis.')
```

## Python modules collection

My favorite daily tool is Python. This plugin includes several essential modules that enhance productivity while working in Sublime Text.

- **chat.py** Integrates ChatGPT directly with the editor.
- **tables.py** Imports Excel and CSV tables into the editor.

These modules requires following dependencies: `openai`, `pandas`, `tabulate`.

You can intall them with this command: `pip install openai pandas tabulate`.

Here's a demo of how they work:

<img src="demo.gif" alt="Demo" style="width:700px;"/>

## Setting up Python integration
You can enhance the functionality by adding custom Python scripts to the `py_modules` directory within the plugin's directory. All global functions and variables in these scripts will be accessible from the plugin.

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

## Contributing

Contributions are welcome! Please submit a pull request or open an issue to discuss any changes.

## License

This project is licensed under the MIT License.
