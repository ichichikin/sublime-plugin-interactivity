# This file is a part of Interactivity plugin

import os


# names of the modules (name.py) and packages (name/__init__.py) in a folder, except those starting with "_"
def _module_names(folder) -> list:
    names = []
    for entry in sorted(os.listdir(folder)):
        if entry.endswith('.py') and os.path.isfile(os.path.join(folder, entry)):
            name = entry[:-3]
        elif os.path.isfile(os.path.join(folder, entry, '__init__.py')):
            name = entry
        else:
            continue
        if name and not name.startswith(('_', '.')) and '.' not in name:
            names.append(name)
    return names


__all__ = _module_names(os.path.dirname(os.path.abspath(__file__)))
