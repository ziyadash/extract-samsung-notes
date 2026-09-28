#!/bin/sh
# filter dump.py output down to app-relevant rows
grep -vE "id='(icon|container|divider|clock|notification_icon_area|notification_icon_area_inner|system_icon_area|system_icons|statusIcons|wifi_[a-z_]*|battery|battery_percentage_view|trigger_layout_container|trigger_layout|default_trigger|default_trigger_stroke|thumbnail_container|inflate_image_only_thumbnail_layout|full_screen_contents|extra)'" | grep -vE "taskbar|task_bar|hotseat|navbar|desc='Recents'|desc='Home'|desc='Back'|Daily Board|All apps|history_recycler|notificationIcons|left_|right_" | cut -c1-210
