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
import time
from unittest.mock import patch, call

import gi
import pkg_resources
import pytest
from gi.repository import Gtk

from qui.updater.intro_page import IntroPage, UpdateRowWrapper, UpdatesAvailable
from qui.updater.progress_page import ProgressPage, QubeUpdateDetails
from qui.updater.tests.conftest import mock_settings
from qui.updater.utils import Theme, ListWrapper, HeaderCheckbox, UpdateStatus

gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')


@patch('threading.Thread')
def test_init_update(
        mock_threading, real_builder, test_qapp,
        mock_next_button, mock_cancel_button, mock_label, all_vms_list):
    class MockThread:
        def __init__(self):
            self.started = False

        def start(self):
            self.started = True

    mock_thread = MockThread()

    mock_threading.return_value = mock_thread

    sut = ProgressPage(
        real_builder, Theme.LIGHT,
        mock_label, mock_next_button, mock_cancel_button
    )

    class MockTreeView:
        def set_model(self, model):
            self.model = model

    sut.progress_list = MockTreeView()

    sut.init_update(all_vms_list, mock_settings)

    assert not mock_next_button.sensitive
    assert mock_cancel_button.sensitive
    assert mock_cancel_button.visible
    assert mock_cancel_button.label == "_Cancel updates"
    assert mock_thread.started

    assert mock_label.text == "Update in progress..."
    assert mock_label.halign == Gtk.Align.CENTER

    assert sut.progress_list.model == all_vms_list.list_store_raw


@patch('gi.repository.GObject.idle_add')
def test_perform_update(
        idle_add, real_builder,
        mock_next_button, mock_cancel_button, mock_label, updatable_vms_list
):
    sut = ProgressPage(
        real_builder, Theme.LIGHT,
        mock_label, mock_next_button, mock_cancel_button
    )

    sut.vms_to_update = updatable_vms_list

    class VMConsumer:
        def __call__(self, vm_rows, *args, **kwargs):
            self.vm_rows = vm_rows

    sut.update_admin_vm = VMConsumer()
    sut.update_templates = VMConsumer()

    sut.perform_update(mock_settings)

    assert len(sut.update_admin_vm.vm_rows) == 1
    assert len(sut.update_templates.vm_rows) == 3

    calls = [call(mock_next_button.set_sensitive, True),
             call(mock_label.set_text, "Update finished"),
             call(mock_cancel_button.set_visible, False)]
    idle_add.assert_has_calls(calls, any_order=True)


@patch('subprocess.check_output')
def test_update_admin_vm(
        mock_subprocess, real_builder, test_qapp,
        mock_next_button, mock_cancel_button, mock_label, mock_list_store
):
    mock_subprocess.return_value = b''
    sut = ProgressPage(
        real_builder, Theme.LIGHT,
        mock_label, mock_next_button, mock_cancel_button
    )

    admins = ListWrapper(UpdateRowWrapper, mock_list_store, sut.theme)
    for vm in test_qapp.domains:
        if vm.klass in ("AdminVM",):
            admins.append_vm(vm)

    sut.update_admin_vm(admins=admins)


def test_get_update_summary(
        real_builder,
        mock_next_button, mock_cancel_button, mock_label, updatable_vms_list
):
    sut = ProgressPage(
        real_builder, Theme.LIGHT,
        mock_label, mock_next_button, mock_cancel_button
    )

    updatable_vms_list[0].set_status(UpdateStatus.NoUpdatesFound)
    updatable_vms_list[1].set_status(UpdateStatus.Error)
    updatable_vms_list[2].set_status(UpdateStatus.Cancelled)
    updatable_vms_list[3].set_status(UpdateStatus.Success)

    sut.vms_to_update = updatable_vms_list

    vm_updated_num, vm_no_updates_num, vm_failed_num = sut.get_update_summary()

    assert vm_updated_num == 1
    assert vm_no_updates_num == 1
    assert vm_failed_num == 2


def test_set_active_row(real_builder, updatable_vms_list):
    sut = QubeUpdateDetails(real_builder)
    row = updatable_vms_list[0]
    sut.set_active_row(row)

    assert sut.details_label.get_text().strip() == "Details for"
    assert sut.qube_label.get_text().strip() == str(row.name)
    assert sut.qube_icon.get_visible()
    assert sut.qube_label.get_visible()
    assert sut.colon.get_visible()
    assert sut.progress_scrolled_window.get_visible()
    assert sut.progress_textview.get_visible()
    assert sut.copy_button.get_visible()


def test_set_active_row_none(real_builder):
    sut = QubeUpdateDetails(real_builder)

    sut.set_active_row(None)

    assert sut.details_label.get_text() == "Select a qube to see details."
    assert not sut.qube_icon.get_visible()
    assert not sut.qube_label.get_visible()
    assert not sut.colon.get_visible()
    assert not sut.progress_scrolled_window.get_visible()
    assert not sut.progress_textview.get_visible()
    assert not sut.copy_button.get_visible()