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
import asyncio
from typing import Optional

from qubesadmin import exc
from qubesadmin.events.utils import wait_for_domain_shutdown

from qubes_config.widgets.utils import get_boolean_feature
from qui.updater.utils import disable_checkboxes, pass_through_event_window, \
    HeaderCheckbox, QubeClass, QubeLabel, QubeName, Theme, get_domain_icon, \
    RowWrapper, ListWrapper


class SummaryPage:

    def __init__(self, builder, theme, next_button):
        self.builder = builder
        self.theme = theme
        self.next_button = next_button
        self.disable_checkboxes = False

        self.updated_tmpls: Optional[list] = None

        self.restart_list = self.builder.get_object("restart_list")
        self.list_store: Optional[ListWrapper] = None

        self.restart_list.connect("row-activated",
                                  self.on_restart_checkbox_toggled)
        self.app_vm_list = self.builder.get_object("restart_list_store")
        restart_checkbox_column = self.builder.get_object(
            "restart_checkbox_column")
        restart_checkbox_column.connect("clicked",
                                        self.on_restart_header_toggled)
        restart_header_button = restart_checkbox_column.get_button()
        restart_header_button.connect('realize', pass_through_event_window)

        self.retart_checkbox_column_button = self.builder.get_object(
            "restart_checkbox_header")
        self.retart_checkbox_column_button.set_inconsistent(True)
        self.retart_checkbox_column_button.connect(
            "toggled", self.on_restart_header_toggled)
        self.restart_checkbox_header = HeaderCheckbox(
            self.retart_checkbox_column_button,
            allowed=["", "", "EXCLUDED"],
            callback_all=lambda plural, num: self.next_button.set_label(
                f"_Finish and restart {num} qube{plural}"),
            callback_some=lambda plural, num: self.next_button.set_label(
                f"_Finish and restart {num} qube{plural}"),
            callback_none=lambda _, __: self.next_button.set_label("_Finish"),
        )

    @disable_checkboxes
    def on_restart_checkbox_toggled(self, _emitter, path, *_args):
        if path is None:
            return

        it = self.app_vm_list.get_iter(path)
        self.app_vm_list[it][1] = \
            not self.app_vm_list[it][1]
        self.refresh_buttons()

    def refresh_buttons(self):
        for row in self.list_store:
            row.refresh_additional_info()
        selected_num = sum(
            row.selected for row in self.list_store)
        if selected_num == 0:
            self.restart_checkbox_header.state = HeaderCheckbox.NONE
        elif selected_num == len(self.app_vm_list):
            self.restart_checkbox_header.state = HeaderCheckbox.ALL
        else:
            self.restart_checkbox_header.state = HeaderCheckbox.SELECTED
        plural = "s" if selected_num > 1 else ""
        self.restart_checkbox_header.set_buttons(plural, selected_num)

    @disable_checkboxes
    def on_restart_header_toggled(self, _emitter):
        if len(self.list_store) == 0:  # to avoid infinite loop
            self.restart_checkbox_header.state = HeaderCheckbox.NONE
            selected_num = 0
        else:
            selected_num = selected_num_old = sum(
                row.selected for row in self.list_store)
            while selected_num == selected_num_old:
                self.restart_checkbox_header.next_state()
                self.select_restart_rows()
                selected_num = sum(
                    row.selected for row in self.list_store)
        plural = "s" if selected_num > 1 else ""
        self.restart_checkbox_header.set_buttons(plural, selected_num)

    @property
    def is_populated(self) -> bool:
        return self.list_store is None

    @disable_checkboxes
    def populate_restart_list(self, restart, vm_list_wrapped, settings):
        self.updated_tmpls = [
            row for row in vm_list_wrapped
            if bool(row.status)
            and QubeClass[row.vm.klass] == QubeClass.TemplateVM
        ]
        possibly_changed_vms = {appvm for template in self.updated_tmpls
                                for appvm in template.vm.appvms
                                }
        self.list_store = ListWrapper(
            RestartRowWrapper, self.app_vm_list, self.theme)

        for vm in possibly_changed_vms:
            if vm.is_running() \
                    and (vm.klass != 'DispVM' or not vm.auto_cleanup):
                self.list_store.append_vm(vm)

        if settings.restart_system_vms:
            self.restart_checkbox_header._allowed[0] = "SYS"
        if settings.restart_other_vms:
            self.restart_checkbox_header._allowed[1] = "OTHER"
        if not restart:
            self.restart_checkbox_header.state = HeaderCheckbox.NONE
        else:
            if settings.restart_system_vms:
                self.restart_checkbox_header.state = HeaderCheckbox.SAFE
            if settings.restart_other_vms:
                self.restart_checkbox_header.state = HeaderCheckbox.EXTENDED
        self.select_restart_rows()

    def select_restart_rows(self):
        for row in self.list_store:
            row.selected = (
                    row.is_sys_qube
                    and not row.is_excluded
                    and "SYS" in self.restart_checkbox_header.allowed
                    or
                    not row.is_sys_qube
                    and not row.is_excluded
                    and "OTHER" in self.restart_checkbox_header.allowed
                    or
                    "EXCLUDED" in self.restart_checkbox_header.allowed
            )

    def perform_restart(self):
        tmpls_to_shutdown = [row.vm
                             for row in self.updated_tmpls
                             if row.vm.is_running()]
        to_restart = [qube_row.vm
                      for qube_row in self.list_store
                      if qube_row.selected
                      and qube_row.is_sys_qube]
        to_shutdown = [qube_row.vm
                       for qube_row in self.list_store
                       if qube_row.selected
                       and not qube_row.is_sys_qube]
        shutdown_domains(tmpls_to_shutdown)
        restart_vms(to_restart)
        shutdown_domains(to_shutdown)


class RestartRowWrapper(RowWrapper):
    COLUMN_NUM = 5
    _SELECTION = 1
    _ICON = 2
    _NAME = 3
    _ADDITIONAL_INFO = 4

    def __init__(self, list_store, vm, theme: Theme):
        label = QubeLabel[vm.label.name]
        raw_row = [
            False,
            get_domain_icon(vm),
            QubeName(vm.name, label.name, theme),
            '',
        ]
        super().__init__(list_store, vm, theme, raw_row)

    @property
    def selected(self):
        return self.qube_row[self._SELECTION]

    @selected.setter
    def selected(self, value):
        self.qube_row[self._SELECTION] = value
        self.refresh_additional_info()

    def refresh_additional_info(self):
        self.qube_row[4] = ''
        if self.selected and not self.is_sys_qube:
            self.qube_row[4] = 'Restarting an app ' \
                               'qube will shut down all running applications'
        if self.selected and self.is_excluded:
            self.qube_row[4] = '<span foreground="red">This qube has been ' \
                               'explicitly disabled from restarting in ' \
                               'settings</span>'

    @property
    def icon(self):
        return self.qube_row[self._ICON]

    @property
    def name(self):
        return self.vm.name

    @property
    def color_name(self):
        return self.qube_row[self._NAME]

    @property
    def additional_info(self):
        return self.qube_row[self._ADDITIONAL_INFO]

    @property
    def is_sys_qube(self):
        return str(self.vm.name).startswith("sys-")

    @property
    def is_excluded(self):
        return not get_boolean_feature(self.vm, 'automatic-restart', True)


# TODO: duplication
def shutdown_domains(to_shutdown):
    """
    Try to shut down vms and wait to finish.
    """
    wait_for = []
    for vm in to_shutdown:
        try:
            vm.shutdown(force=True)
            wait_for.append(vm)
        except exc.QubesVMError:
            pass

    asyncio.run(wait_for_domain_shutdown(wait_for))

    return wait_for


# TODO: duplication
def restart_vms(to_restart):
    """
    Try to restart vms.
    """
    shutdowns = shutdown_domains(to_restart)

    # restart shutdown qubes
    for vm in shutdowns:
        try:
            vm.start()
        except exc.QubesVMError:
            pass
