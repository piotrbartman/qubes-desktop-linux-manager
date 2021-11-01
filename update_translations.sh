#!/bin/bash

xgettext -d desktop-linux-manager -o locale/desktop-linux-manager.pot qui/*py qui/tray/*py qui/*glade

find locale/* -maxdepth 2 -mindepth 2 -type f -iname '*.po' -exec msgmerge --update {} locale/desktop-linux-manager.pot \;
