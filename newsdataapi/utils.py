import sys


PY3 = sys.version_info[0] == 3


if PY3:

    def is_valid_string(lang):
        return isinstance(lang, str)

    def is_valid_integer(lang):
        return isinstance(lang, int)
