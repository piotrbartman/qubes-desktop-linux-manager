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
import subprocess
import gi

from datetime import datetime, timedelta
from typing import Union, Optional
gi.require_version('Gtk', '3.0')  # isort:skip
from gi.repository import Gtk  # isort:skip

from qubes_config.widgets.gtk_utils import load_icon
from qubesadmin import exc

from qui.updater.utils import disable_checkboxes, HeaderCheckbox, \
    pass_through_event_window, QubeLabel, Theme, \
    QubeName, label_color_theme, UpdateStatus, RowWrapper, \
    ListWrapper, on_head_checkbox_toggled


class IntroPage:
    """
    First content page of updater.

    Show the list of updatable vms with an update info.
    """

    def __init__(self, builder, theme, next_button):
        self.builder = builder
        self.theme = theme
        self.next_button = next_button
        self.disable_checkboxes = False
        self.active = True

        self.page: Gtk.Box = self.builder.get_object("list_page")
        self.stack: Gtk.Stack = self.builder.get_object("main_stack")
        self.vm_list: Gtk.TreeView = self.builder.get_object("vm_list")
        self.list_store: Optional[ListWrapper] = None

        checkbox_column: Gtk.TreeViewColumn = self.builder.get_object(
            "checkbox_column")
        checkbox_column.connect("clicked", self.on_header_toggled)
        header_button = checkbox_column.get_button()

        header_button.connect('realize', pass_through_event_window)

        self.checkbox_column_button: Gtk.CheckButton = self.builder.get_object(
            "checkbox_header")
        self.checkbox_column_button.set_inconsistent(True)
        self.checkbox_column_button.connect("toggled", self.on_header_toggled)
        self.head_checkbox = HeaderCheckbox(
            self.checkbox_column_button,
            allowed=["YES", "MAYBE", "NO"],
            callback_all=lambda *_args: self.next_button.set_sensitive(True),
            callback_some=lambda *_args: self.next_button.set_sensitive(True),
            callback_none=lambda *_args: self.next_button.set_sensitive(False),
        )

        self.vm_list.connect("row-activated", self.on_checkbox_toggled)

        self.info_how_it_works: Gtk.Label = self.builder.get_object(
            "info_how_it_works")
        self.info_how_it_works.set_label(
            self.info_how_it_works.get_label().format(
                MAYBE='<span foreground="Orange"><b>MAYBE</b></span>'))

        self.restart_button: Gtk.CheckButton = self.builder.get_object(
            "restart_button")

    def populate_vm_list(self, qapp, settings):
        """Adds to list any updatable vms with a updates info."""
        self.list_store = ListWrapper(
            UpdateRowWrapper, self.vm_list.get_model(), self.theme)

        for vm in qapp.domains:
            if vm.klass == 'AdminVM':
                try:
                    state = bool(vm.features.get('updates-available', False))
                except exc.QubesDaemonCommunicationError:
                    state = False
                self.list_store.append_vm(vm, state)

        for vm in qapp.domains:
            if getattr(vm, 'updateable', False) and vm.klass != 'AdminVM':
                self.list_store.append_vm(vm)

        self.refresh_update_list(settings.update_if_stale)

    def refresh_update_list(self, update_if_stale):
        """
        Refreshes "Updates Available" column if settings changed.
        """
        if not self.active:
            return

        output = subprocess.check_output(
            ['qubes-vm-update', '--dry-run',
             '--update-if-stale', str(update_if_stale)])

        to_update = [
            vm_name.strip() for vm_name
            in output.decode().split("\n", maxsplit=1)[0]
                .split(":", maxsplit=1)[1].split(",")]

        for row in self.list_store:
            row.updates_available = bool(row.vm.name in to_update)

    def get_vms_to_update(self) -> ListWrapper:
        """Returns list of vms selected to be updated"""
        return self.list_store.get_selected()

    @property
    def is_populated(self) -> bool:
        """Returns True if updatable vms list is populated."""
        return self.list_store is not None

    @property
    def is_visible(self):
        """Returns True if page is shown by stack."""
        return self.stack.get_visible_child() == self.page

    @disable_checkboxes
    def on_checkbox_toggled(self, _emitter, path, *_args):
        """Handles (un)selection of single row."""
        if path is None:
            return

        self.list_store.invert_selection(path)
        selected_num = sum(row.selected for row in self.list_store)
        if selected_num == len(self.list_store):
            self.head_checkbox.state = HeaderCheckbox.ALL
        elif selected_num == 0:
            self.head_checkbox.state = HeaderCheckbox.NONE
        else:
            self.head_checkbox.state = HeaderCheckbox.SELECTED
        self.head_checkbox.set_buttons()

    @disable_checkboxes
    def on_header_toggled(self, _emitter):
        """Handles clicking on header checkbox.

        Cycle between selection of:
         <1> vms with `updates_available` (YES)
         <2> <1> + vms no checked for updates for a while (YES and MAYBE)
         <3> all vms (YES , MAYBE and NO)
         <4> no vm. (nothing)

        If the user has selected any vms that do not match the defined states,
        the cycle will start from (1).
        """
        on_head_checkbox_toggled(
            self.list_store, self.head_checkbox, self.select_rows)

    def select_rows(self):
        for row in self.list_store:
            row.selected = row.updates_available.value \
                           in self.head_checkbox.allowed


class UpdateRowWrapper(RowWrapper):
    COLUMN_NUM = 9
    _SELECTION = 1
    _ICON = 2
    _NAME = 3
    _UPDATES_AVAILABLE = 4
    _LAST_UPDATES_CHECK = 5
    _LAST_UPDATE = 6
    _UPDATE_PROGRESS = 7
    _STATUS = 8

    def __init__(self, list_store, vm, theme: Theme, to_update: bool):
        updates_available = bool(vm.features.get('updates-available', False))
        if to_update and not updates_available:
            updates_available = None
        selected = updates_available is True

        last_updates_check = vm.features.get('last-updates-check', None)
        last_update = vm.features.get('last-update', None)

        label = QubeLabel[str(vm.label)]
        icon = load_icon(vm.icon)
        name = QubeName(vm.name, label.name, theme)

        raw_row = [
            selected,
            icon,
            name,
            UpdatesAvailable(updates_available, theme),
            Date(last_updates_check),
            Date(last_update),
            0,
            UpdateStatus.Undefined,
        ]

        super().__init__(list_store, vm, theme, raw_row)

        self.buffer: str = ""

    def append_text_view(self, text):
        self.buffer += text

    @property
    def selected(self):
        return self.raw_row[self._SELECTION]

    @selected.setter
    def selected(self, value):
        self.raw_row[self._SELECTION] = value

    @property
    def icon(self):
        return self.raw_row[self._ICON]

    @property
    def name(self):
        return self.raw_row[self._NAME].name

    @property
    def color_name(self):
        return self.raw_row[self._NAME]

    @property
    def updates_available(self):
        return self.raw_row[self._UPDATES_AVAILABLE]

    @updates_available.setter
    def updates_available(self, value):
        updates_available = bool(
            self.vm.features.get('updates-available', False))
        if value and not updates_available:
            updates_available = None
        self.raw_row[self._UPDATES_AVAILABLE] = \
            UpdatesAvailable(updates_available, self.theme)

    @property
    def last_updates_check(self):
        return self.raw_row[self._LAST_UPDATES_CHECK]

    @property
    def last_update(self):
        return self.raw_row[self._LAST_UPDATE]

    def get_update_progress(self):
        return self.raw_row[self._UPDATE_PROGRESS]

    @property
    def status(self) -> UpdateStatus:
        return self.raw_row[self._STATUS]

    def set_status(self, status_code: UpdateStatus):
        self.raw_row[self._STATUS] = status_code

    def set_update_progress(self, progress):
        self.raw_row[self._UPDATE_PROGRESS] = progress


class Date:
    """
    Prints Date in desired way: unknown, today, yesterday, normal date.

    Comparable.
    """
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.date_format_source = "%Y-%m-%d %H:%M:%S"
        if len(args) == 1 and args[0] is None:
            self.datetime = datetime.min
        elif len(args) == 1 and isinstance(args[0], str):
            self.datetime = datetime.strptime(args[0], self.date_format_source)
        else:
            self.datetime = datetime(*args, *kwargs)
        self.date_format = "%Y-%m-%d"

    @classmethod
    def from_datetime(cls, datetime_: datetime):
        self = cls(1, 1, 1)
        self.datetime = datetime_
        return self

    def __str__(self):
        date_str = self.datetime.strftime(self.date_format)
        today_str = datetime.today().strftime(self.date_format)
        yesterday = datetime.today() - timedelta(days=1)
        yesterday_str = yesterday.strftime(self.date_format)
        unknown_str = datetime.min.strftime(self.date_format)
        if date_str == today_str:
            return "today"
        if date_str == yesterday_str:
            return "yesterday"
        if date_str == unknown_str:
            return "unknown"
        return date_str

    def __eq__(self, other):
        return self.datetime == other.datetime

    def __lt__(self, other):
        return self.datetime < other.datetime


class UpdatesAvailable:
    """
    Formatted info about updates.

    Comparable.
    """
    def __init__(self, value: Union[Optional[bool], str], theme: Theme):
        super().__init__()
        if isinstance(value, str):
            if value.upper() == "NO":
                value = False
            elif value.upper() == "YES":
                value = True
            else:
                value = None

        if value is None:
            self.value = "MAYBE"
            self.order = 1
            self.color = "orange"
        elif value:
            self.value = "YES"
            self.order = 0
            self.color = "green"
        else:
            self.value = "NO"
            self.order = 2
            self.color = label_color_theme(theme, "black")

    def __str__(self):
        return f'<span foreground="{self.color}"><b>' \
               + self.value + '</b></span>'

    def __eq__(self, other):
        return self.order == other.order

    def __lt__(self, other):
        return self.order < other.order
