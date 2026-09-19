import pytest

from proteo.core.steamvdf import (
    VdfError, dumps, find, loads, set_value, with_wrapper, without_wrapper,
)

SAMPLE = '''"UserLocalConfigStore"
{
\t"Software"
\t{
\t\t"Valve"
\t\t{
\t\t\t"Steam"
\t\t\t{
\t\t\t\t"apps"
\t\t\t\t{
\t\t\t\t\t"1174180"
\t\t\t\t\t{
\t\t\t\t\t\t"LaunchOptions"\t\t"WINEDLLOVERRIDES=\\"DWrite.dll=n,b\\" %command%"
\t\t\t\t\t}
\t\t\t\t\t"292030"
\t\t\t\t\t{
\t\t\t\t\t\t"LaunchOptions"\t\t""
\t\t\t\t\t}
\t\t\t\t}
\t\t\t}
\t\t}
\t}
}'''


# --------------------------------------------------------------------------
# parsing and serialising
# --------------------------------------------------------------------------

def test_round_trip_is_byte_identical():
    # Steam's own formatting has to survive: this file is rewritten wholesale
    assert dumps(loads(SAMPLE)) == SAMPLE


def test_escapes_survive_a_round_trip():
    tree = loads(SAMPLE)
    options = find(tree, "UserLocalConfigStore", "Software", "Valve", "Steam",
                   "apps", "1174180", "LaunchOptions")
    assert options == 'WINEDLLOVERRIDES="DWrite.dll=n,b" %command%'
    assert dumps(loads(dumps(tree))) == SAMPLE


def test_repeated_keys_and_order_are_preserved():
    text = '"root"\n{\n\t"a"\t\t"1"\n\t"a"\t\t"2"\n\t"b"\t\t"3"\n}'
    assert loads(text) == [("root", [("a", "1"), ("a", "2"), ("b", "3")])]
    assert dumps(loads(text)) == text


def test_comments_and_unquoted_tokens():
    tree = loads('// leading comment\n"root"\n{\n\tkey value\n}')
    assert tree == [("root", [("key", "value")])]


def test_malformed_input_is_rejected():
    for bad in ('"root" {', '"root"\n{\n}\n}', '"key"'):
        with pytest.raises(VdfError):
            loads(bad)


# --------------------------------------------------------------------------
# navigation
# --------------------------------------------------------------------------

def test_find_is_case_insensitive():
    tree = loads('"Root"\n{\n\t"Steam"\n\t{\n\t\t"x"\t\t"1"\n\t}\n}')
    assert find(tree, "root", "steam", "X") == "1"
    assert find(tree, "root", "nope") is None
    assert find(tree, "root", "steam", "x", "deeper") is None


def test_set_value_replaces_in_place_and_keeps_case():
    node = [("a", "1"), ("LaunchOptions", "old"), ("b", "2")]
    set_value(node, "launchoptions", "new")
    assert node == [("a", "1"), ("LaunchOptions", "new"), ("b", "2")]
    set_value(node, "c", "3")
    assert node[-1] == ("c", "3")


# --------------------------------------------------------------------------
# the launch-options rule
# --------------------------------------------------------------------------

def test_wrapper_added_to_empty_options():
    assert with_wrapper("") == "proteo profile -- %command%"
    assert with_wrapper("   ") == "proteo profile -- %command%"


def test_wrapper_goes_before_command_keeping_env_assignments():
    # the whole point: env vars must stay in front, or they become arguments
    assert with_wrapper('WINEDLLOVERRIDES="DWrite.dll=n,b" %command%') == \
        'WINEDLLOVERRIDES="DWrite.dll=n,b" proteo profile -- %command%'
    assert with_wrapper("mangohud %command% -skipintro") == \
        "mangohud proteo profile -- %command% -skipintro"


def test_options_without_command_keep_their_arguments_after_it():
    assert with_wrapper("-windowed -novid") == \
        "proteo profile -- %command% -windowed -novid"


def test_wrapper_is_not_added_twice():
    once = with_wrapper("gamemoderun %command%")
    assert with_wrapper(once) == once


def test_removal_restores_the_original_exactly():
    for original in ('WINEDLLOVERRIDES="DWrite.dll=n,b" %command%',
                     "mangohud %command% -skipintro",
                     "gamemoderun %command%"):
        assert without_wrapper(with_wrapper(original)) == original


def test_removal_of_a_wrapper_only_value_leaves_nothing():
    assert without_wrapper("proteo profile -- %command%") == ""


def test_removal_leaves_unhooked_options_alone():
    assert without_wrapper("mangohud %command%") == "mangohud %command%"
    assert without_wrapper("") == ""
