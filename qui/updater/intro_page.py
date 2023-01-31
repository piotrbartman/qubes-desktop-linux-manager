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
from datetime import datetime, timedelta
from typing import Union, Optional
from gi.repository import GObject
from qubesadmin import exc

from qui.updater.utils import disable_checkboxes, HeaderCheckbox, \
    pass_through_event_window, QubeLabel, sort_func, Theme, get_domain_icon, \
    QubeName, label_color_theme, QubeClass, UpdateStatus


class IntroPage:

    def __init__(self, builder, theme, next_button):
        self.builder = builder
        self.theme = theme
        self.next_button = next_button
        self.disable_checkboxes = False
        self.active = True

        self.vm_list = self.builder.get_object("vm_list")

        checkbox_column = self.builder.get_object("checkbox_column")
        checkbox_column.connect("clicked", self.on_header_toggled)
        header_button = checkbox_column.get_button()

        header_button.connect('realize', pass_through_event_window)

        self.checkbox_column_button = self.builder.get_object("checkbox_header")
        self.checkbox_column_button.set_inconsistent(True)
        self.checkbox_column_button.connect("toggled", self.on_header_toggled)
        self.update_checkbox_header = HeaderCheckbox(
            self.checkbox_column_button,
            allowed=["YES", "MAYBE", "NO"],
            callback_all=lambda: self.next_button.set_sensitive(True),
            callback_some=lambda: self.next_button.set_sensitive(True),
            callback_none=lambda: self.next_button.set_sensitive(False),
        )

        self.vm_list.connect("row-activated", self.on_checkbox_toggled)

    def populate_vm_list(self, qapp, settings):
        self.list_store = self.vm_list.get_model()
        self.list_store_wrapped = []

        self.list_store.set_sort_func(0, sort_func, 0)
        self.list_store.set_sort_func(3, sort_func, 3)
        self.list_store.set_sort_func(4, sort_func, 4)
        self.list_store.set_sort_func(5, sort_func, 5)
        self.list_store.set_sort_func(6, sort_func, 6)
        self.list_store.set_sort_func(8, sort_func, 8)
        for vm in qapp.domains:
            if vm.klass == 'AdminVM':
                try:
                    state = bool(vm.features.get('updates-available', False))
                except exc.QubesDaemonCommunicationError:
                    state = False
                qube_row = UpdateRowWrapper(
                    self.list_store, vm, state, self.theme)
                self.list_store_wrapped.append(qube_row)

        for vm in qapp.domains:
            if getattr(vm, 'updateable', False) and vm.klass != 'AdminVM':
                qube_row = UpdateRowWrapper(
                    self.list_store, vm, False, self.theme)
                settings.available_vms.append(vm)
                self.list_store_wrapped.append(qube_row)

        self.refresh_update_list(settings.update_if_stale)

    def refresh_update_list(self, update_if_stale):
        if not self.active:
            return

        output = subprocess.check_output(
            ['qubes-vm-update', '--dry-run',
             '--update-if-stale', str(update_if_stale)])

        to_update = [vm_name.strip() for vm_name
                     in output.decode().split("\n")[0].split(":")[1].split(",")]

        for row in self.list_store_wrapped:
            row.updates_available = bool(row.qube.name in to_update)

    def get_vms_to_update(self):
        selected_rows = [row for row in self.list_store_wrapped
                         if row.selected]
        to_remove = [row for row in self.list_store_wrapped
                     if not row.selected]
        for elem in to_remove:
            elem.delete()
        return selected_rows

    @disable_checkboxes
    def on_checkbox_toggled(self, _emitter, path, *_args):
        if path is None:
            return

        it = self.list_store.get_iter(path)
        self.list_store[it][0].selected = \
            not self.list_store[it][0].selected
        selected_num = sum(row.selected for row in self.list_store_wrapped)
        if selected_num == len(self.list_store_wrapped):
            self.update_checkbox_header.state = HeaderCheckbox.ALL
        elif selected_num == 0:
            self.update_checkbox_header.state = HeaderCheckbox.NONE
        else:
            self.update_checkbox_header.state = HeaderCheckbox.SELECTED
        self.update_checkbox_header.set_buttons()

    @disable_checkboxes
    def on_header_toggled(self, _emitter):
        if len(self.list_store_wrapped) == 0:
            self.update_checkbox_header.state = HeaderCheckbox.NONE
        else:
            selected_num = selected_num_old = sum(
                row.selected for row in self.list_store_wrapped)
            while selected_num == selected_num_old:
                self.update_checkbox_header.next_state()
                for row in self.list_store_wrapped:
                    row.selected = row.updates_available.value \
                                   in self.update_checkbox_header.allowed
                selected_num = sum(
                    row.selected for row in self.list_store_wrapped)

        self.update_checkbox_header.set_buttons()


class UpdateRowWrapper(GObject.GObject):
    def __init__(self, list_store, qube, to_update: bool, theme: Theme):
        super().__init__()
        self.list_store = list_store
        self.qube = qube
        updates_available = bool(qube.features.get('updates-available', False))
        if to_update and not updates_available:
            updates_available = None
        selected = updates_available is True
        last_updates_check = qube.features.get('last-updates-check', None)
        last_update = qube.features.get('last-update', None)
        self.buffer: str = ""
        label = QubeLabel[self.qube.label.name]
        self.theme = theme
        qube_row = [
            self,
            selected,
            get_domain_icon(qube),
            QubeName(qube.name, label.name, theme),
            UpdatesAvailable(updates_available, theme),
            Date(last_updates_check),
            Date(last_update),
            0,
            UpdateStatus.Undefined,
        ]
        self.list_store.append(qube_row)
        self.qube_row = self.list_store[-1]

    def append_text_view(self, text):
        self.buffer += text

    @property
    def selected(self):
        return self.qube_row[1]

    @selected.setter
    def selected(self, value):
        self.qube_row[1] = value

    @property
    def icon(self):
        return self.qube_row[2]

    @property
    def name(self):
        return self.qube_row[3].name

    @property
    def color_name(self):
        return self.qube_row[3]

    @property
    def updates_available(self):
        return self.qube_row[4]

    @updates_available.setter
    def updates_available(self, value):
        updates_available = bool(
            self.qube.features.get('updates-available', False))
        if value and not updates_available:
            updates_available = None
        self.qube_row[4] = UpdatesAvailable(updates_available, self.theme)

    @property
    def last_updates_check(self):
        return self.qube_row[5]

    @property
    def last_update(self):
        return self.qube_row[6]

    def get_update_progress(self):
        return self.qube_row[7]

    @property
    def status(self) -> UpdateStatus:
        return self.qube_row[8]

    def set_status(self, status_code: UpdateStatus):
        self.qube_row[8] = status_code

    def __eq__(self, other):
        self_class = QubeClass[self.qube.klass]
        other_class = QubeClass[other.qube.klass]
        if self_class == other_class:
            self_label = QubeLabel[self.qube.label.name]
            other_label = QubeLabel[other.qube.label.name]
            return self_label.value == other_label.value
        return False

    def __lt__(self, other):
        self_class = QubeClass[self.qube.klass]
        other_class = QubeClass[other.qube.klass]
        if self_class == other_class:
            self_label = QubeLabel[self.qube.label.name]
            other_label = QubeLabel[other.qube.label.name]
            return self_label.value < other_label.value
        return self_class.value < other_class.value

    def set_update_progress(self, progress):
        self.qube_row[7] = progress

    def delete(self):
        self.list_store.remove(self.qube_row.iter)


class Date(GObject.GObject):
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
        never_str = datetime.min.strftime(self.date_format)
        if date_str == today_str:
            return "today"
        elif date_str == yesterday_str:
            return "yesterday"
        elif date_str == never_str:
            return "never"
        else:
            return date_str

    def __eq__(self, other):
        return self.datetime == other.datetime

    def __lt__(self, other):
        return self.datetime < other.datetime


class UpdatesAvailable:
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
