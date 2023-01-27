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


import pkg_resources

from gi.repository import Gtk, GObject

from qubes_config.global_config.vm_flowbox import VMFlowboxHandler


class Settings:
    def __init__(self, main_window, qapp):
        GObject.signal_new('child-removed',
                           Gtk.FlowBox,
                           GObject.SignalFlags.RUN_LAST, GObject.TYPE_PYOBJECT,
                           (GObject.TYPE_PYOBJECT,))
        self.qapp = qapp
        self.builder = Gtk.Builder()

        self.builder.set_translation_domain("desktop-linux-manager")
        self.builder.add_from_file(pkg_resources.resource_filename(
            'qui', 'updater_settings.glade'))
        self.settings_window = self.builder.get_object("main_window")
        self.settings_window.set_transient_for(main_window)
        self.settings_window.connect("delete-event", self.close_window)
        self.cancel_button = self.builder.get_object("button_settings_cancel")
        self.cancel_button.connect(
            "clicked", lambda _: self.settings_window.close())
        self.save_button = self.builder.get_object("button_settings_save")
        self.save_button.connect(
            "clicked", lambda _: self.settings_window.close())

        self.settings_restart_system = self.builder.get_object(
            "settings_restart_system")

        self.settings_restart_other = self.builder.get_object(
            "settings_restart_other")

        self.available_vms = [
            vm for vm in self.qapp.domains
            if getattr(vm, 'updateable', False) and vm.klass != 'AdminVM']
        self.available_vms.append(self.qapp.domains['devel-debian'])
        self.enable_some_handler = VMFlowboxHandler(
            self.builder, self.qapp, "restart_exceptions",
            [], lambda vm: vm in self.available_vms)
        self.restart_exceptions_page = self.builder.get_object(
            "restart_exceptions_page")

        self.settings_restart_other.connect(
            "toggled", self.show_restart_exceptions)

        self.settings_limit = self.builder.get_object("settings_limit")
        self.settings_limit.connect("toggled", self.limit_toggled)

        self.days_without_update = self.builder.get_object(
            "days_without_update")
        adj = Gtk.Adjustment(7, 1, 100, 1, 1, 1)
        self.days_without_update.configure(adj, 1, 0)

        self.max_concurrency = self.builder.get_object("max_concurrency")
        adj = Gtk.Adjustment(4, 1, 17, 1, 1, 1)
        self.max_concurrency.configure(adj, 1, 0)

    def show_restart_exceptions(self, _emitter=None):
        if self.settings_restart_other.get_active():
            self.restart_exceptions_page.show_all()
        else:
            self.restart_exceptions_page.hide()

    def limit_toggled(self, _emitter=None):
        self.max_concurrency.set_sensitive(
            self.settings_limit.get_active()
        )

    def show(self):
        self.settings_window.show_all()
        self.show_restart_exceptions()
        self.limit_toggled()

    def close_window(self, _emitter, _):
        self.settings_window.hide()
        return True
