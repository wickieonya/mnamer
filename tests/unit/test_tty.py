from mnamer import tty
from mnamer.exceptions import MnamerAbortException, MnamerSkipException


def test_chars():
    tty.verbose = False
    tty.no_style = False
    expected = {
        "arrow": "\x1b[35m❱\x1b[0m",
        "block": "█",
        "left-edge": "▐",
        "right-edge": "▌",
        "selected": "●",
        "unselected": "○",
    }
    actual = tty._chars()
    assert actual == expected


def test_chars__no_style():
    tty.verbose = False
    tty.no_style = True
    expected = {
        "arrow": ">",
        "block": "#",
        "left-edge": "|",
        "right-edge": "|",
        "selected": "*",
        "unselected": ".",
    }
    actual = tty._chars()
    assert actual == expected


def test_abort_helpers():
    tty.verbose = False
    tty.no_style = False
    helpers = tty._abort_helpers()
    assert len(helpers) == 2
    assert helpers[0].label == "skip"
    assert helpers[0].value == MnamerSkipException
    assert helpers[0]._bracketed is False
    assert helpers[1].label == "quit"
    assert helpers[1].value == MnamerAbortException
    assert helpers[1]._bracketed is False


def test_abort_helpers__no_style():
    tty.verbose = False
    tty.no_style = True
    helpers = tty._abort_helpers()
    assert len(helpers) == 2
    assert helpers[0].label == "skip"
    assert helpers[0].value == MnamerSkipException
    assert helpers[0]._bracketed is True
    assert helpers[1].label == "quit"
    assert helpers[1].value == MnamerAbortException
    assert helpers[1]._bracketed is True
