# coding=utf-8
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2023  Piotr Bartman <prbartman@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301,
# USA.
from unittest.mock import patch

import gi
import pkg_resources
import pytest
from gi.overrides import Gtk

from qui.updater.intro_page import IntroPage, UpdateRowWrapper, UpdatesAvailable
from qui.updater.utils import Theme, ListWrapper, HeaderCheckbox

gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')


class MockButton:  # TODO
    def __init__(self):
        self.value = None

    def set_sensitive(self, value: bool):
        self.value = value


class MockSettings:
    def __init__(self):
        self.update_if_stale = 7


class MockListStore:
    def __init__(self):
        self.raw_rows = []

    def get_model(self):
        return self

    def get_iter(self, path):
        return path[0]

    def __getitem__(self, item):
        return self.raw_rows[item]

    def append(self, row):
        self.raw_rows.append(row)
        # TODO row.iter

    def remove(self, idx):
        self.raw_rows.remove(idx)

    def set_sort_func(self, _col, _sort_func, _data):
        pass


@patch('subprocess.check_output')
def test_populate_vm_list(mock_subprocess, test_qapp):
    mock_button = MockButton()

    builder = Gtk.Builder()
    builder.set_translation_domain("desktop-linux-manager")
    builder.add_from_file(pkg_resources.resource_filename(
        'qui', 'updater.glade'))
    sut = IntroPage(builder, Theme.LIGHT, mock_button)
    test_qapp.expected_calls[
        ('test-standalone', "admin.vm.feature.Get", 'updates-available', None)
    ] = b"0\x00" + str(1).encode()
    # inconsistent output of qubes-vm-update, but it does not matter
    mock_subprocess.return_value = b'Following templates will be updated:'

    sut.populate_vm_list(test_qapp, MockSettings())
    assert len(sut.list_store) == 4
    assert len(sut.get_vms_to_update()) == 1

    test_qapp.expected_calls[
        ('fedora-36', "admin.vm.feature.Get", 'updates-available', None)
    ] = b"0\x00" + str(1).encode()

    sut.populate_vm_list(test_qapp, MockSettings())
    assert len(sut.list_store) == 4
    assert len(sut.get_vms_to_update()) == 2


@pytest.mark.parametrize(
    "updates_available, expectations",
    (
        pytest.param((2, 6), (0, 2, 6, 12, 0)),
        pytest.param((6, 0), (0, 6, 12, 0)),
    ),
)
def test_on_header_toggled(test_qapp, updates_available, expectations):
    vm_list = MockListStore()

    mock_button = MockButton()

    builder = Gtk.Builder()
    builder.set_translation_domain("desktop-linux-manager")
    builder.add_from_file(pkg_resources.resource_filename(
        'qui', 'updater.glade'))
    sut = IntroPage(builder, Theme.LIGHT, mock_button)

    # populate_vm_list
    sut.list_store = ListWrapper(UpdateRowWrapper, vm_list, sut.theme)
    for vm in test_qapp.domains:
        sut.list_store.append_vm(vm)

    assert len(sut.list_store) == 12

    for i, row in enumerate(sut.list_store):
        if i < updates_available[0]:
            value = True
        elif i < updates_available[1]:
            value = None
        else:
            value = False
        row.raw_row[row._UPDATES_AVAILABLE] = UpdatesAvailable(
            value, Theme.LIGHT)
    sut.update_checkbox_header.state = HeaderCheckbox.NONE

    for expected in expectations:
        selected_num = len([row for row in sut.list_store if row.selected])
        assert selected_num == expected
        assert sut.checkbox_column_button.get_inconsistent() \
               and expected not in (0, 12) \
               or sut.checkbox_column_button.get_active() \
               and expected == 12 \
               or not sut.checkbox_column_button.get_active() \
               and expected == 0
        assert mock_button.value or expected == 0
        sut.on_header_toggled(None)
