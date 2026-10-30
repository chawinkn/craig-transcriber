import io
import re
import subprocess
import sys
import tokenize

BAD = re.compile(
    r"(?<![\w#])#\d+\b|\b\d{4}-\d{2}-\d{2}\b|\b(?:measured|reviewer|review said|used to|previously)\b",
    re.I,
)


def py_comments(text):
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.COMMENT:
            yield tok.start[0], tok.string


def c_comments(text, line_comments=True):
    # No regex literal in the sources contains // or /*, so strings are the only thing to skip.
    i, line, n = 0, 1, len(text)
    while i < n:
        c = text[i]
        if c in "\"'`":
            j = i + 1
            while j < n and text[j] != c and not (text[j] == "\n" and c != "`"):
                j += 2 if text[j] == "\\" else 1
            line += text.count("\n", i, j)
            i = j + 1
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            yield line, text[i:j]
            line += text.count("\n", i, j)
            i = j
        elif line_comments and text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            yield line, text[i:j]
            i = j
        else:
            line += c == "\n"
            i += 1


def comments(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if path.endswith(".py"):
        return py_comments(text)
    return c_comments(text, line_comments=path.endswith(".js"))


def find(paths):
    for path in paths:
        for line, comment in comments(path):
            if BAD.search(comment):
                yield f"{path}:{line}: {comment}"


def tracked():
    out = subprocess.check_output(["git", "ls-files", "*.py", "static/*.js", "static/*.css"], text=True)
    return out.split()


if __name__ == "__main__":
    bad = list(find(sys.argv[1:] or tracked()))
    print("\n".join(bad))
    sys.exit(1 if bad else 0)
