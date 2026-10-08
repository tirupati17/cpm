"""Write one command's part of a shared Markdown report, leaving the rest alone.

Two commands can fill one file (`cpm appstore prices` and `cpm play prices`
both write a pricing table): each owns the text between its own markers and
re-running either replaces only that part.

    <!-- cpm:appstore-prices -->
    ...
    <!-- /cpm:appstore-prices -->
"""
from pathlib import Path


def replace_section(document, name, body):
    """The document with the `name` section replaced (or appended). Pure."""
    start, end = f'<!-- cpm:{name} -->', f'<!-- /cpm:{name} -->'
    block = f'{start}\n{body.rstrip()}\n{end}\n'
    if start in document and end in document:
        head, rest = document.split(start, 1)
        tail = rest.split(end, 1)[1].lstrip('\n')
        return head + block + ('\n' + tail if tail else '')
    if document and not document.endswith('\n'):
        document += '\n'
    return document + ('\n' if document else '') + block


def write_section(path, name, body):
    path = Path(path)
    current = path.read_text(encoding='utf-8') if path.is_file() else ''
    path.write_text(replace_section(current, name, body), encoding='utf-8')
    return path
