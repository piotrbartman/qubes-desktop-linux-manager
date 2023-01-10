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
        self.builder = Gtk.Builder()
        self.builder.set_translation_domain("desktop-linux-manager")
        self.builder.add_from_file(pkg_resources.resource_filename(
            __name__, 'updater_settings.glade'))
        self.settings_window = self.builder.get_object("main_window")
        self.settings_window.set_transient_for(main_window)
        self.settings_window.connect("delete-event", self.close_window)
        self.cancel_button = self.builder.get_object("button_settings_cancel")
        self.cancel_button.connect(
            "clicked", lambda _: self.settings_window.close())
        self.save_button = self.builder.get_object("button_settings_save")
        self.save_button.connect(
            "clicked", lambda _: self.settings_window.close())
        self.available_vms = []
        self.enable_some_handler = VMFlowboxHandler(
            self.builder, qapp, "restart_exceptions",
            [], lambda vm: vm in self.available_vms)

    def show(self):
        self.settings_window.show_all()

    def close_window(self, _emitter, _):
        self.settings_window.hide()
        return True