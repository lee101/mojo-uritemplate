from __future__ import annotations

import ctypes
import itertools
import struct

import pytest
import uritemplate as upstream

import mojo_uritemplate as mojo
from mojo_uritemplate._lib import lib
from mojo_uritemplate.orderedset import OrderedSet
from mojo_uritemplate.template import URIVariable


RFC_VALUES = {
    "count": ["one", "two", "three"],
    "dom": ["example", "com"],
    "dub": "me/too",
    "hello": "Hello World!",
    "half": "50%",
    "var": "value",
    "who": "fred",
    "base": "http://example.com/home/",
    "path": "/foo/bar",
    "list": ["red", "green", "blue"],
    "keys": {"semi": ";", "dot": ".", "comma": ","},
    "x": "1024",
    "y": "768",
    "empty": "",
    "undef": None,
}

RFC_CASES = [
    ("{var}", "value"),
    ("{hello}", "Hello%20World%21"),
    ("{half}", "50%25"),
    ("O{empty}X", "OX"),
    ("O{undef}X", "OX"),
    ("{x,y}", "1024,768"),
    ("{+var}", "value"),
    ("{+hello}", "Hello%20World!"),
    ("{+path}/here", "/foo/bar/here"),
    ("here?ref={+path}", "here?ref=/foo/bar"),
    ("X{#var}", "X#value"),
    ("X{#hello}", "X#Hello%20World!"),
    ("map?{x,y}", "map?1024,768"),
    ("{.who}", ".fred"),
    ("{.who,who}", ".fred.fred"),
    ("{/who}", "/fred"),
    ("{/who,who}", "/fred/fred"),
    ("{;x,y}", ";x=1024;y=768"),
    ("{;x,y,empty}", ";x=1024;y=768;empty"),
    ("{?x,y}", "?x=1024&y=768"),
    ("{?x,y,empty}", "?x=1024&y=768&empty="),
    ("{&x,y,empty}", "&x=1024&y=768&empty="),
    ("{var:3}", "val"),
    ("{list}", "red,green,blue"),
    ("{list*}", "red,green,blue"),
    ("{keys}", "comma,%2C,dot,.,semi,%3B"),
    ("{keys*}", "comma=%2C,dot=.,semi=%3B"),
    ("{+path:6}/here", "/foo/b/here"),
    ("{#path:6}/here", "#/foo/b/here"),
    ("{.list}", ".red,green,blue"),
    ("{.list*}", ".red.green.blue"),
    ("{/list}", "/red,green,blue"),
    ("{/list*}", "/red/green/blue"),
    ("{;list}", ";list=red,green,blue"),
    ("{;list*}", ";list=red;list=green;list=blue"),
    ("{?list}", "?list=red,green,blue"),
    ("{?list*}", "?list=red&list=green&list=blue"),
    ("{&list*}", "&list=red&list=green&list=blue"),
    ("{.keys}", ".comma,%2C,dot,.,semi,%3B"),
    ("{.keys*}", ".comma=%2C.dot=..semi=%3B"),
    ("{/keys}", "/comma,%2C,dot,.,semi,%3B"),
    ("{/keys*}", "/comma=%2C/dot=./semi=%3B"),
    ("{;keys}", ";keys=comma,%2C,dot,.,semi,%3B"),
    ("{;keys*}", ";comma=%2C;dot=.;semi=%3B"),
    ("{?keys}", "?keys=comma,%2C,dot,.,semi,%3B"),
    ("{?keys*}", "?comma=%2C&dot=.&semi=%3B"),
    ("{&keys*}", "&comma=%2C&dot=.&semi=%3B"),
]


@pytest.mark.parametrize(("template", "expected"), RFC_CASES)
def test_published_rfc_examples(template, expected):
    assert mojo.expand(template, RFC_VALUES) == expected
    assert upstream.expand(template, RFC_VALUES) == expected


@pytest.mark.parametrize("operator", ["", "+", "#", ".", "/", ";", "?", "&", "=", "!", "@", "|", ","])
def test_all_operators_match_upstream_for_value_shapes(operator):
    values = [
        None,
        "",
        "a b/c",
        "café",
        "%2F x",
        0,
        False,
        [],
        [None],
        ["", None, "a/b"],
        {},
        {"b": "x y", "a": None},
        [("z", "1"), ("a", "2")],
    ]
    for modifier, value in itertools.product(("", "*", ":1", ":0", ":-1"), values):
        template = "{" + operator + "x" + modifier + "}"
        try:
            expected = upstream.expand(template, x=value)
        except Exception as expected_error:
            with pytest.raises(type(expected_error)):
                mojo.expand(template, x=value)
        else:
            assert mojo.expand(template, x=value) == expected


@pytest.mark.parametrize(
    ("template", "values"),
    [
        ("/users{/id}{?fields,active}", {"id": 42, "fields": ["name", "email"], "active": False}),
        ("{?pairs*}", {"pairs": [("first", 1), ("second", "two")]}),
        ("{/segments*}", {"segments": ["one", None, "three"]}),
        ("{+already}", {"already": "%2F unescaped space"}),
        ("{word:2}/{word:-1}", {"word": "éclair"}),
        ("{;word:-1}", {"word": "a"}),
        ("{data}", {"data": b"hello world"}),
        ("{;zero,false,empty}", {"zero": 0, "false": False, "empty": ""}),
        ("a{{x}", {"{x": "nested"}),
        ("{missing=legacy}", {}),
        ("{missing=legacy}", {"missing": None}),
        ("{missing=legacy}", {"missing": 0}),
        ("{missing=legacy}", {"missing": False}),
        ("{missing=legacy}", {"missing": ""}),
        ("{missing=legacy}", {"missing": b""}),
        ("{missing=legacy}", {"missing": []}),
        ("{missing=legacy}", {"missing": {}}),
        ("{x}", {b"x": "bytes-key"}),
        ("{1}", {1: "integer-key"}),
    ],
)
def test_edge_cases_match_upstream(template, values):
    assert mojo.expand(template, values) == upstream.expand(template, values)


@pytest.mark.parametrize(
    ("template", "values"),
    [
        ("/repos{/owner}{/repo}", {"owner": "python-hyper"}),
        ("/search{?q,page}", {}),
        ("/search{?q,page}", {"q": "uri templates"}),
        ("{x}{/y}{?z}", {"x": ""}),
        ("plain", {}),
    ],
)
def test_partial_matches_upstream(template, values):
    actual = mojo.partial(template, values)
    expected = upstream.partial(template, values)
    assert isinstance(actual, mojo.URITemplate)
    assert str(actual) == str(expected)
    assert actual.variable_names == OrderedSet(expected.variable_names)


def test_kwargs_override_dictionary():
    assert mojo.expand("{x}", {"x": "first"}, x="second") == "second"
    assert mojo.expand("{x}", {"x": "first"}, x="second") == upstream.expand(
        "{x}", {"x": "first"}, x="second"
    )


def test_template_protocol_and_metadata():
    template = mojo.URITemplate("/repos{/owner}{/repo}{?owner}")
    same = mojo.URITemplate(str(template))
    assert repr(template) == 'URITemplate("/repos{/owner}{/repo}{?owner}")'
    assert template == same
    assert hash(template) == hash(same)
    assert list(template.variable_names) == ["owner", "repo"]
    assert [str(item) for item in template.variables] == [
        "/owner",
        "/repo",
        "?owner",
    ]


def test_variables_preserve_first_seen_order():
    actual = mojo.variables("{x}{?y,x}{/z}")
    expected = upstream.variables("{x}{?y,x}{/z}")
    assert isinstance(actual, OrderedSet)
    assert list(actual) == list(expected) == ["x", "y", "z"]


def test_uri_variable_public_expansion():
    variable = URIVariable("?x,list")
    expected = upstream.variable.URIVariable("?x,list")
    values = {"x": "a b", "list": ["red", "green"]}
    assert variable.variable_names == expected.variable_names
    assert variable.expand(values) == expected.expand(values)


def test_large_output_retries_without_truncation():
    name = "n" * 400
    values = {name: ["x"] * 500}
    template = "{?" + name + "*}"
    actual = mojo.expand(template, values)
    assert actual == upstream.expand(template, values)
    assert len(actual) > 200_000


@pytest.mark.parametrize("name", ["abc", "abcd", "abcde", "abcdefghijk"])
def test_native_simd_copy_and_scalar_tail(name):
    template = "{?" + name + "}"
    values = {name: "value"}
    assert mojo.expand(template, values) == upstream.expand(template, values)
    assert str(mojo.partial(template, {})) == str(upstream.partial(template, {}))


@pytest.mark.parametrize(
    "wire",
    [
        b"\x01\x00\x00\x00",
        b"\x01\x00\x00\x00\xff\xff\xff\xff",
        b"\x01\x00\x00\x00\x01\x00\x00\x00x",
        b"\x01\x00\x00\x00\x01\x00\x00\x00x\x01\xff\xff\xff\xff",
        b"\x01\x00\x00\x00\x01\x00\x00\x00x\x02\x01\x00\x00\x00",
        b"\x01\x00\x00\x00\x01\x00\x00\x00x\x02\x01\x00\x00\x00\x02",
        b"\x01\x00\x00\x00\x01\x00\x00\x00x\x03\x01\x00\x00\x00"
        b"\xff\xff\xff\xff",
        b"\x01\x00\x00\x00\x01\x00\x00\x00x\x08",
        b"\x00\x00\x00\x00trailing",
    ],
)
def test_native_rejects_malformed_wire_without_reading_past_it(wire):
    template = ctypes.create_string_buffer(b"{x}")
    wire_buffer = ctypes.create_string_buffer(wire)
    destination = ctypes.create_string_buffer(64)
    status = lib().mut_expand(
        ctypes.addressof(template),
        3,
        ctypes.addressof(wire_buffer),
        len(wire),
        ctypes.addressof(destination),
        len(destination),
        0,
    )
    assert status == -2


def test_native_rejects_null_pointers_and_invalid_lengths():
    valid_wire = ctypes.create_string_buffer(struct.pack("<I", 0))
    destination = ctypes.create_string_buffer(1)
    assert lib().mut_expand(
        0, 0, ctypes.addressof(valid_wire), 4,
        ctypes.addressof(destination), 1, 0,
    ) == -1
    template = ctypes.create_string_buffer(b"x")
    assert lib().mut_expand(
        ctypes.addressof(template), -1, ctypes.addressof(valid_wire), 4,
        ctypes.addressof(destination), 1, 0,
    ) == -1
    assert lib().mut_expand(
        ctypes.addressof(template), 1, ctypes.addressof(valid_wire), 4,
        0, 0, 0,
    ) == -1


def test_malformed_and_literal_braces_match_upstream():
    for template in ("", "plain", "{", "{}", "{x", "a{{x}", "a}b"):
        assert mojo.expand(template, x="value") == upstream.expand(
            template, x="value"
        )
