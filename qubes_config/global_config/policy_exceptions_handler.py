# -*- encoding: utf8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2022 Marta Marczykowska-Górecka
#                               <marmarta@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation; either version 2.1 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License along
# with this program; if not, see <http://www.gnu.org/licenses/>.
"""
Class for handling a list of exceptions, such as for updateProxy.
"""
from typing import Optional, List, Callable

from qrexec.policy.parser import Rule

from .policy_handler import PolicyHandler
from .rule_list_widgets import NoActionListBoxRow, RuleListBoxRow, ErrorRuleRow

import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

class PolicyExceptionsHandler:
    """
    Class for handling a list of policy exceptions
    """
    def __init__(self, gtk_builder: Gtk.Builder, prefix: str,
                 row_func: Callable[[Rule, bool], Gtk.ListBoxRow],
                 new_rule: Callable[..., Rule],
                 exclude_rule: Optional[Callable[[Rule], bool]] = None):
        """
        :param gtk_builder: Gtk.Builder instance
        :param prefix: prefix for widgets; expects a prefix_exception_list
        ListBox and prefix_add_rule_button Button
        :param row_func: function that returns expected ListBoxRows
        :param new_rule: function that returns a new Rule
        :param exclude_rule: optional function that excludes some rules from
        being shown; if True, exclude rule
        """
        self.exclude_rule = exclude_rule
        self.row_func = row_func  # takes a Rule and new/true/false
        self.new_rule = new_rule

        self.rule_list: Gtk.ListBox = gtk_builder.get_object(
            f'{prefix}_exception_list')

        self.add_button: Gtk.Button = gtk_builder.get_object(
            f'{prefix}_add_rule_button')

        self.error_box: Gtk.Box = gtk_builder.get_object(f'{prefix}_error_box')
        self.error_list: Gtk.ListBox = gtk_builder.get_object(
            f'{prefix}_error_list')

        # connect events
        self.rule_list.connect('row-activated', self._rule_clicked)
        self.add_button.connect("clicked", self.add_new_rule)

        self._errors: List[Rule] = []

    def load_rules(self, rules: List[Rule]):
        """Load provided rules."""
        actual_rules = []

        for rule in rules:
            if self.exclude_rule and self.exclude_rule(rule):
                continue
            actual_rules.append(rule)

        for child in self.rule_list.get_children():
            self.rule_list.remove(child)

        self.clear_errors()
        for rule in actual_rules:
            try:
                self.rule_list.add(self.row_func(rule, False))
            except Exception:  # pylint: disable=broad-except
                self.add_error(rule)

    def add_new_rule(self, *_args):
        """Add a new rule."""
        self.close_all_edits()
        new_row = self.row_func(self.new_rule(), True)
        self.rule_list.add(new_row)
        new_row.activate()

    def _rule_clicked(self, _list_box, row: NoActionListBoxRow, *_args):
        if row.editing:
            # if the current row was clicked, nothing should happen
            return
        self.close_all_edits()
        row.set_edit_mode(True)

    @property
    def current_rows(self) -> List[RuleListBoxRow]:
        """Get currently existing rows."""
        return self.rule_list.get_children()

    def close_all_edits(self):
        """Close all edited rows."""
        PolicyHandler.close_rows_in_list(self.rule_list.get_children())

    def add_error(self, rule: Rule):
        self._errors.append(rule)
        self.error_box.set_visible(True)
        self.error_box.show_all()
        self.error_list.add(ErrorRuleRow(rule))
        self.error_list.show_all()

    def clear_errors(self):
        self._errors.clear()
        self.error_box.set_visible(False)
        for child in self.error_list.get_children():
            self.error_list.remove(child)

# FOR DISPVMS: Open in Dispvm like update proxy
# open in vm: just pick default target? and deny? default is ask
