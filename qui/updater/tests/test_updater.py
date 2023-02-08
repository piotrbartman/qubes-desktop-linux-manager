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
from unittest.mock import patch, ANY

import gi

from qui.updater.updater import QubesUpdater

gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk

# this entire file has a peculiar arrangement with mock signal registration:
# to enable tests from this file to run alone,
# a test_builder fixture is requested because it will try to register
# signals in "test" mode

@patch('subprocess.check_output')
# @patch('qubes_config.global_config.global_config.show_error')
def test_global_config_init(mock_subprocess,
                            test_qapp):
    mock_subprocess.return_value = b'Following templates will be updated: fedora-35,fedora-36,test-standalone'
    app = QubesUpdater(test_qapp)
    # do not call do_activate - it will make Gtk confused and, in case
    # of errors, spawn an entire screenful of windows
    test_qapp.expected_calls[
        ('test-standalone', "admin.vm.feature.Get", 'updates-available', None)
    ] = b"0\x00" + str(1).encode()

    app.perform_setup()
    print(app.intro_page.get_vms_to_update())
    assert False
    # assert test_builder
    #
    # # switch across pages, nothing should happen
    # while app.main_notebook.get_nth_page(
    #         app.main_notebook.get_current_page()).get_name() != 'thisdevice':
    #     app.main_notebook.next_page()
    #
    # # find clipboard
    # app.main_notebook.set_current_page(0)
    #
    # while app.main_notebook.get_nth_page(
    #         app.main_notebook.get_current_page()).get_name() != 'clipboard':
    #     app.main_notebook.next_page()
    #
    # clipboard_page_num = app.main_notebook.get_current_page()
    # handler = app.get_current_page()
    # assert isinstance(handler, ClipboardHandler)
    #
    # assert handler.copy_combo.get_active_id() == 'default (Ctrl+Shift+C)'
    # handler.copy_combo.set_active_id('Ctrl+Win+C')
    #
    # # try to move away from page, we should get a warning
    # with patch('qubes_config.global_config.global_config.show_dialog') \
    #         as mock_ask:
    #     mock_ask.return_value = Gtk.ResponseType.NO
    #     app.main_notebook.set_current_page(clipboard_page_num + 1)
    #
    # assert app.main_notebook.get_current_page() == clipboard_page_num + 1
    # app.main_notebook.set_current_page(clipboard_page_num)
    #
    # assert handler.copy_combo.get_active_id() == 'default (Ctrl+Shift+C)'
    # handler.copy_combo.set_active_id('Ctrl+Win+C')
    #
    # # try to move away from page, we should get a warning
    # with patch('qubes_config.global_config.global_config.show_dialog') \
    #         as mock_ask, patch('qubes_config.global_config.basics_handler.'
    #            'apply_feature_change') as mock_apply:
    #     mock_ask.return_value = Gtk.ResponseType.YES
    #     app.main_notebook.set_current_page(clipboard_page_num + 1)
    #     mock_apply.assert_called_with(
    #         test_qapp.domains['dom0'], 'gui-default-secure-copy-sequence',
    #         'Ctrl-Mod4-c')
    #
    # mock_error.assert_not_called()