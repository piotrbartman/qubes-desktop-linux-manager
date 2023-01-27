# coding=utf-8
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2022  Piotr Bartman <prbartman@invisiblethingslab.com>
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
from typing import Optional

import pkg_resources

from gi.repository import Gtk, GObject

from qubes_config.global_config.vm_flowbox import VMFlowboxHandler
from qubes_config.widgets.utils import get_boolean_feature, \
    apply_feature_change, get_feature


class Settings:
    def __init__(self, main_window, qapp):
        GObject.signal_new('child-removed',
                           Gtk.FlowBox,
                           GObject.SignalFlags.RUN_LAST, GObject.TYPE_PYOBJECT,
                           (GObject.TYPE_PYOBJECT,))
        self.qapp = qapp
        self.vm = self.qapp.domains[self.qapp.local_name]
        self.builder = Gtk.Builder()

        self.builder.set_translation_domain("desktop-linux-manager")
        self.builder.add_from_file(pkg_resources.resource_filename(
            'qui', 'updater_settings.glade'))
        self.settings_window = self.builder.get_object("main_window")
        self.settings_window.set_transient_for(main_window)
        self.settings_window.connect("delete-event", self.close_without_saving)
        self.cancel_button = self.builder.get_object("button_settings_cancel")
        self.cancel_button.connect(
            "clicked", lambda _: self.settings_window.close())
        self.save_button = self.builder.get_object("button_settings_save")
        self.save_button.connect("clicked", self.save_and_close)

        self.restart_system_checkbox = self.builder.get_object(
            "restart_system")

        self.restart_other_checkbox = self.builder.get_object(
            "restart_other")

        self.available_vms = [
            vm for vm in self.qapp.domains
            if getattr(vm, 'updateable', False) and vm.klass != 'AdminVM']

        self.excluded_vms = [
            vm for vm in self.available_vms
            if not get_boolean_feature(vm, 'automatic-restart', True)]

        self.available_vms.append(self.qapp.domains['devel-debian'])
        self.exceptions = VMFlowboxHandler(
            self.builder, self.qapp, "restart_exceptions",
            self.excluded_vms, lambda qube: qube in self.available_vms)
        self.restart_exceptions_page = self.builder.get_object(
            "restart_exceptions_page")

        self.restart_other_checkbox.connect(
            "toggled", self.show_restart_exceptions)

        self.limit_concurrency_checkbox = self.builder.get_object(
            "limit_concurrency")
        self.limit_concurrency_checkbox.connect(
            "toggled", self.limit_concurrency_toggled)

        self.days_without_update_button = self.builder.get_object(
            "days_without_update")
        adj = Gtk.Adjustment(7, 1, 100, 1, 1, 1)
        self.days_without_update_button.configure(adj, 1, 0)

        self.max_concurrency_button = self.builder.get_object("max_concurrency")
        adj = Gtk.Adjustment(4, 1, 17, 1, 1, 1)
        self.max_concurrency_button.configure(adj, 1, 0)

    @property
    def update_if_stale(self) -> int:
        return int(get_feature(self.vm, "qubes-vm-update-update-if-stale", 7))

    @property
    def restart_system_vms(self) -> bool:
        return get_boolean_feature(
            self.vm, "qubes-vm-update-restart-system", True)

    @property
    def restart_other_vms(self) -> bool:
        return get_boolean_feature(
            self.vm, "qubes-vm-update-restart-other", False)

    @property
    def max_concurrency(self) -> Optional[int]:
        result = get_feature(self.vm, "qubes-vm-update-max-concurrency", None)
        if result is None:
            return result
        return int(result)

    def load_settings(self):
        self._init_update_if_stale = self.update_if_stale
        self.days_without_update_button.set_value(self._init_update_if_stale)

        self._init_restart_system_vms = self.restart_system_vms
        self._init_restart_other_vms = self.restart_other_vms
        self.restart_system_checkbox.set_active(self._init_restart_system_vms)
        self.restart_other_checkbox.set_active(self._init_restart_other_vms)

        self._init_max_concurrency = self.max_concurrency
        self._init_limit_concurrency = self._init_max_concurrency is not None
        self.limit_concurrency_checkbox.set_active(self._init_limit_concurrency)
        if self._init_limit_concurrency:
            self.max_concurrency_button.set_value(self._init_max_concurrency)

    def show_restart_exceptions(self, _emitter=None):
        if self.restart_other_checkbox.get_active():
            self.restart_exceptions_page.show_all()
            self.exceptions.reset()
        else:
            self.restart_exceptions_page.hide()

    def limit_concurrency_toggled(self, _emitter=None):
        self.max_concurrency_button.set_sensitive(
            self.limit_concurrency_checkbox.get_active()
        )

    def show(self):
        self.load_settings()
        self.settings_window.show_all()
        self.show_restart_exceptions()
        self.limit_concurrency_toggled()

    def close_without_saving(self, _emitter, _):
        self.settings_window.hide()
        return True

    def save_and_close(self, _emitter):
        """Save any changes."""
        vm = self.qapp.domains[self.qapp.local_name]

        update_if_stale = int(self.days_without_update_button.get_value())
        if self._init_update_if_stale != update_if_stale:
            if update_if_stale == 7:
                update_if_stale = None
            apply_feature_change(
                vm, "qubes-vm-update-update-if-stale", update_if_stale)

        restart_system_vms = self.restart_system_checkbox.get_active()
        if self._init_restart_system_vms != restart_system_vms:
            if restart_system_vms:
                restart_system_vms = None
            apply_feature_change(
                vm, "qubes-vm-update-restart-system", restart_system_vms)

        restart_other_vms = self.restart_other_checkbox.get_active()
        if self._init_restart_other_vms != restart_other_vms:
            if not restart_other_vms:
                restart_other_vms = None
            apply_feature_change(
                vm, "qubes-vm-update-restart-other", restart_other_vms)

        limit_concurrency = self.limit_concurrency_checkbox.get_active()
        if self._init_limit_concurrency != limit_concurrency:
            if limit_concurrency:
                max_concurrency = int(self.max_concurrency_button.get_value())
            else:
                max_concurrency = None
            if self._init_max_concurrency != max_concurrency:
                apply_feature_change(
                    vm, "qubes-vm-update-max-concurrency", max_concurrency)

        if self.exceptions.is_changed():
            for vm in self.exceptions.added_vms:
                apply_feature_change(vm, 'automatic-restart', False)
            for vm in self.exceptions.removed_vms:
                apply_feature_change(vm, 'automatic-restart', None)
            self.exceptions.save()

        self.settings_window.close()
