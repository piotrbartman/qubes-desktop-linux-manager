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
import pytest
from unittest.mock import patch

from qui.updater.summary_page import SummaryPage
from qui.updater.utils import Theme, HeaderCheckbox, UpdateStatus


@patch('qui.updater.summary_page.SummaryPage.refresh_buttons')
def test_show(
        refresh_buttons, real_builder, test_qapp, appvms_list,
        mock_next_button, mock_cancel_button
):
    test_qapp.expected_calls[
        ('test-blue', "admin.vm.feature.Get", 'restart-after-update', None)
    ] = b"0\x00" + "".encode()

    sut = SummaryPage(
        real_builder, Theme.LIGHT, mock_next_button, mock_cancel_button,
        back_by_row_selection=lambda *args: None  # callback
    )

    sut.list_store = appvms_list

    sut.show(0, 1, 2)

    assert sut.stack.get_visible_child() == sut.page
    assert sut.label_summary.get_text() == \
           "0 qubes updated successfully.\n" \
           "1 qube attempted to update but found no updates.\n" \
           "2 qubes failed to update."
    assert sut.cancel_button.visible
    assert sut.cancel_button.label == "_Back"
    refresh_buttons.assert_called_once()


def test_on_header_toggled(
        real_builder, test_qapp, appvms_list,
        mock_next_button, mock_cancel_button
):
    test_qapp.expected_calls[
        ('test-blue', "admin.vm.feature.Get", 'restart-after-update', None)
    ] = b"0\x00" + "".encode()

    sut = SummaryPage(
        real_builder, Theme.LIGHT, mock_next_button, mock_cancel_button,
        back_by_row_selection=lambda *args: None  # callback
    )

    sut.list_store = appvms_list
    all_num = len(appvms_list)
    sut.head_checkbox._allowed[0] = "SYS"
    sys_num = 3
    sut.head_checkbox._allowed[1] = "OTHER"
    non_excluded_num = 6

    sut.head_checkbox.state = HeaderCheckbox.NONE

    for expected in (0, sys_num, non_excluded_num, all_num, 0):
        selected_num = len([row for row in sut.list_store if row.selected])
        assert selected_num == expected
        assert sut.head_checkbox_button.get_inconsistent() \
               and expected not in (0, all_num) \
               or sut.head_checkbox_button.get_active() \
               and expected == all_num \
               or not sut.head_checkbox_button.get_active() \
               and expected == 0

        sut.on_header_toggled(None)


def test_on_checkbox_toggled(
        real_builder, test_qapp, appvms_list,
        mock_next_button, mock_cancel_button, mock_settings
):
    sut = SummaryPage(
        real_builder, Theme.LIGHT, mock_next_button, mock_cancel_button,
        back_by_row_selection=lambda *args: None  # callback
    )

    sut.list_store = appvms_list
    sut.head_checkbox._allowed[0] = "SYS"
    sut.head_checkbox._allowed[1] = "OTHER"

    sut.head_checkbox.state = HeaderCheckbox.NONE
    sut.head_checkbox.set_buttons()

    # no selected row
    assert not sut.head_checkbox_button.get_inconsistent()
    assert not sut.head_checkbox_button.get_active()

    # only one row selected
    sut.on_checkbox_toggled(_emitter=None, path=(3,))

    assert sut.head_checkbox_button.get_inconsistent()

    for i in range(len(sut.list_store)):
        sut.on_checkbox_toggled(_emitter=None, path=(i,))

    # almost all rows selected (except one)
    assert sut.head_checkbox_button.get_inconsistent()

    sut.on_checkbox_toggled(_emitter=None, path=(3,))

    # all rows selected
    assert not sut.head_checkbox_button.get_inconsistent()
    assert sut.head_checkbox_button.get_active()

    sut.on_checkbox_toggled(_emitter=None, path=(3,))

    # almost all rows selected (except one)
    assert sut.head_checkbox_button.get_inconsistent()

    for i in range(len(sut.list_store)):
        if i == 3:
            continue
        sut.on_checkbox_toggled(_emitter=None, path=(i,))

    # no selected row
    assert not sut.head_checkbox_button.get_inconsistent()
    assert not sut.head_checkbox_button.get_active()


# expected data based on test_qapp setup
UP_VMS = 7
UP_SYS_VMS = 3
UP_APP_VMS = 4


@pytest.mark.parametrize(
    "restart_system_vms, restart_other_vms, excluded, expected",
    (
        pytest.param(True, True, (), UP_VMS),
        pytest.param(True, False, (), UP_SYS_VMS),
        pytest.param(False, False, (), 0),
        pytest.param(False, True, (), UP_APP_VMS),
        pytest.param(True, True, ("test-blue",), UP_VMS - 1),
        pytest.param(True, False, ("test-blue",), UP_SYS_VMS),
        pytest.param(False, True, ("sys-usb",), UP_APP_VMS),
        pytest.param(True, False, ("sys-usb",), UP_SYS_VMS - 1),
    ),
)
def test_populate_restart_list(
        restart_system_vms, restart_other_vms, excluded, expected,
        real_builder, test_qapp, updatable_vms_list,
        mock_next_button, mock_cancel_button, mock_settings, mock_tree_view
):
    mock_settings.restart_other_vms = restart_other_vms
    mock_settings.restart_system_vms = restart_system_vms
    for exclude in excluded:
        test_qapp.expected_calls[
            (exclude, "admin.vm.feature.Get", 'restart-after-update', None)
        ] = b"0\x00" + "".encode()

    sut = SummaryPage(
        real_builder, Theme.LIGHT, mock_next_button, mock_cancel_button,
        back_by_row_selection=lambda *args: None  # callback
    )
    sut.summary_list = mock_tree_view

    for row in updatable_vms_list:
        row.set_status(UpdateStatus.Success)
        if row.vm.klass == "TemplateVM":
            for i, appvm in enumerate(row.vm.appvms):
                if i < UP_VMS:
                    appvm.is_running = lambda *_args: True
                else:
                    appvm.is_running = lambda *_args: False

    sut.populate_restart_list(True, updatable_vms_list, mock_settings)

    assert len(sut.list_store) == UP_VMS
    assert sum(row.selected for row in sut.list_store) == expected
