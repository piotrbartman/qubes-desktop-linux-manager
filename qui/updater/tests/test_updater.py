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
from unittest.mock import patch, call

from qui.updater.updater import QubesUpdater, parse_args


@patch('logging.FileHandler')
@patch('logging.getLogger')
@patch('qui.updater.intro_page.IntroPage.populate_vm_list')
def test_setup(populate_vm_list, _mock_logging, __mock_logging, test_qapp):
    sut = QubesUpdater(test_qapp, parse_args(()))
    sut.perform_setup()
    calls = [call(sut.qapp, sut.settings)]
    populate_vm_list.assert_has_calls(calls)
