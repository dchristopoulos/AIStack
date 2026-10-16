"""A project is known by its remote, or on one computer by its path (ADR-0026).

A remote can carry a token, so every rejection is checked for not quoting what it was sent.
"""

import logging
import uuid

import pytest

from aistack.commons.exceptions import ValidationError
from aistack.services import projects

TOKEN = "ghs_s3cr3tT0ken"


@pytest.mark.parametrize("remote", [
    f"https://user:{TOKEN}@github.com/Owner/Repo.git",
    "https://github.com/Owner/Repo",
    "https://github.com/owner/repo/",
    "http://github.com:8080/owner/repo.git",
    "git@github.com:Owner/Repo.git",
    "github.com:owner/repo",
    "ssh://git@github.com:22/owner/repo",
    "git+ssh://git@github.com/owner/repo.git",
    "git://github.com/owner/repo.git",
    f"https://github.com/owner/repo.git?access_token={TOKEN}",
    f"https://github.com/owner/repo#{TOKEN}",
])
def test_every_spelling_of_one_remote_is_one_project(remote):
    assert projects.project_key(remote) == "github.com/owner/repo"


def test_a_nested_path_keeps_every_segment():
    assert projects.project_key("https://gitlab.com/Group/Sub/Repo.git") == \
        "gitlab.com/group/sub/repo"


@pytest.mark.parametrize("remote", [
    "file:///srv/r.git",
    "/srv/r.git",
    "../r",
    "~/code/r",
    "C:\\code\\r",
    "C:/code/r",
    "\\\\server\\share\\r",
])
def test_a_remote_on_disk_is_this_computers_alone(remote):
    assert projects.project_key(remote) is None


def test_a_local_key_names_the_computer_and_not_the_path():
    machine = uuid.uuid4()
    key = projects.local_project_key(machine, "/Users/maria/code/r")

    assert key.startswith(f"local/{machine}/")
    assert "maria" not in key
    assert len(key) <= projects.KEY_MAX_LENGTH
    assert key == projects.local_project_key(machine, "/Users/maria/code/r")
    assert key != projects.local_project_key(machine, "/Users/maria/code/other")
    assert key != projects.local_project_key(uuid.uuid4(), "/Users/maria/code/r")


@pytest.mark.parametrize("remote", [
    "",
    "   ",
    f"https://user:{TOKEN}@github.com/owner/repo\n",
    f"https://user:{TOKEN}@github.com/own\x00er/repo",
    f"https://user:{TOKEN}@github.com/",
    f"https://user:{TOKEN}@/owner/repo",
    f"https://user:{TOKEN}@github.com/" + "a" * 300,
    f"https://user:{TOKEN}@github.com/" + "a" * 3000,
    f"git@github.com:owner/re po{TOKEN}",
])
def test_a_remote_that_cannot_be_read_is_refused_without_quoting_it(remote, caplog):
    caplog.set_level(logging.DEBUG)
    with pytest.raises(ValidationError) as refused:
        projects.project_key(remote)

    message = refused.value.message
    assert TOKEN not in message
    for part in filter(None, remote.replace("/", " ").replace(":", " ").split()):
        if len(part) > 3:
            assert part not in message, part
    assert TOKEN not in caplog.text


@pytest.mark.parametrize(("key_or_path", "name"), [
    ("github.com/owner/aistack", "aistack"),
    ("/Users/maria/code/aistack", "aistack"),
    ("/Users/maria/code/aistack/", "aistack"),
    ("C:\\code\\billing-api", "billing-api"),
    ("/srv/r.git", "r"),
])
def test_a_project_is_named_after_its_last_segment(key_or_path, name):
    assert projects.project_name(key_or_path) == name


def test_a_long_folder_name_is_cut_to_what_the_page_shows():
    assert len(projects.project_name("/code/" + "a" * 200)) == projects.NAME_MAX_LENGTH


def test_here_keeps_the_path_and_keys_the_remote():
    here = projects.validated_here("/Users/maria/code/aistack",
                                   f"https://x:{TOKEN}@github.com/Owner/AIStack.git")

    assert here == projects.Here(path="/Users/maria/code/aistack",
                                 key="github.com/owner/aistack")


@pytest.mark.parametrize("path", ["~/code/r", "/srv/r", "C:\\code\\r", "D:/r", "\\\\nas\\r"])
def test_here_takes_an_absolute_path_or_one_under_home(path):
    assert projects.validated_here(path, None).path == path


@pytest.mark.parametrize("path", [
    "~", "~/", "$HOME", "/Users/maria", "/Users/maria/", "/home/maria", "/root",
    "C:\\Users\\maria", "c:/users/maria/",
])
def test_the_home_folder_is_not_a_project(path):
    with pytest.raises(ValidationError, match="home folder"):
        projects.validated_here(path, None)


@pytest.mark.parametrize("path", [
    "", "code/r", "./r", "/srv/\x1b[31mr", "/srv/r\n", "/" + "a" * projects.PATH_MAX_LENGTH,
])
def test_a_path_that_is_not_an_absolute_printable_one_is_refused_without_quoting_it(path):
    with pytest.raises(ValidationError) as refused:
        projects.validated_here(path, None)

    for part in filter(None, path.split("/")):
        if len(part) > 3:
            assert part not in refused.value.message
