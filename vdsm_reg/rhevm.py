#!/usr/bin/python
#
# Copyright 2011 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA
#
# Refer to the README and COPYING files for full details of the license
#
# Written by Joey Boggs <jboggs@redhat.com>
#

import os
import sys
from ovirtnode.ovirtfunctions import ovirt_store_config, is_valid_host_or_ip, \
                                     is_valid_port, PluginBase, log, network_up, \
                                     password_check, augtool
from ovirtnode.password import set_password

from snack import ButtonChoiceWindow, Entry, Grid, Label, Checkbox, \
                  FLAG_DISABLED, FLAGS_SET, customColorset, Textbox
import subprocess

sys.path.append('/usr/share/vdsm-reg')
import deployUtil

sys.path.append('/usr/share/vdsm')
import constants

VDSM_CONFIG = "/etc/vdsm/vdsm.conf"
VDSM_REG_CONFIG = "/etc/vdsm-reg/vdsm-reg.conf"
VDC_HOST_PORT = 8443

fWriteConfig = 0
def set_defaults():
    vdsm_config_file = open(VDSM_CONFIG, "w")
    vdsm_config = """[vars]
trust_store_path = /etc/pki/vdsm/
ssl = true

[addresses]
management_port = 54321
"""
    vdsm_config_file.write(vdsm_config)
    vdsm_config_file.close()

def write_vdsm_config(rhevm_host, rhevm_port):
    if not os.path.exists(VDSM_CONFIG):
        os.system("touch " + VDSM_CONFIG)
    if os.path.getsize(VDSM_CONFIG) == 0:
        set_defaults()
        ovirt_store_config(VDSM_CONFIG)
        log("RHEV agent configuration files created.")
    else:
        log("RHEV agent configuration files already exist.")

    ret = os.system("ping -c 1 " + rhevm_host + " &> /dev/null")
    if ret == 0:
        sed_cmd = "sed -i --copy \"s/\(^vdc_host_name=\)\(..*$\)/vdc_host_name="+rhevm_host+"/\" " + VDSM_REG_CONFIG
        ret = os.system(sed_cmd)
        if ret == 0:
            log("The RHEV Manager's address is set: %s\n" % rhevm_host)
        if rhevm_port != "":
            sed_cmd = "sed -i --copy \"s/\(^vdc_host_port=\)\(..*$\)/vdc_host_port="+str(rhevm_port)+"/\" " + VDSM_REG_CONFIG
            os.system(sed_cmd)
            log("The RHEV Manager's port set: %s\n" % rhevm_port)
            fWriteConfig=1
    else:
        log("Either " + rhevm_host + " is an invalid address or the RHEV Manager unresponsive.\n")
        return False

    if fWriteConfig == 1:
        log("Saving vdsm-reg.conf\n")
        if ovirt_store_config(VDSM_REG_CONFIG):
            log("vdsm-reg.conf Saved\n")
            return True

def get_rhevm_config():
    vdsm_config = open(VDSM_REG_CONFIG)
    config = {}
    config["vdc_host_port"] = VDC_HOST_PORT
    for line in vdsm_config:
        line = line.strip().replace(" ","").split("=")
        if "vdc_host_name" in line:
            item, config["vdc_host_name"] = line[0], line[1]
        if "vdc_host_port" in line:
            item, config["vdc_host_port"] = line[0], line[1]
    vdc_server = config["vdc_host_name"] + ":" + config["vdc_host_port"]
    vdsm_config.close()
    return vdc_server

class Plugin(PluginBase):
    """Plugin for RHEV-M configuration.
    """

    def __init__(self, ncs):
        PluginBase.__init__(self, "RHEV-M", ncs)

    def form(self):
        elements = Grid(2, 8)
        is_network_up = network_up()
        if is_network_up:
            header_message = "RHEV-M Configuration"
        else:
            header_message = "Network Down, RHEV-M Configuration Disabled"
        heading = Label(header_message)
        self.ncs.screen.setColor(customColorset(1), "black", "magenta")
        heading.setColors(customColorset(1))
        elements.setField(heading, 0, 0, anchorLeft = 1)
        rhevm_grid = Grid(2,2)
        rhevm_grid.setField(Label("Management Server:"), 0, 0, anchorLeft = 1)
        self.rhevm_server = Entry(25, "")
        self.rhevm_server.setCallback(self.valid_rhevm_server_callback)
        rhevm_grid.setField(Label("Management Server Port:"), 0, 1, anchorLeft = 1)
        self.rhevm_server_port = Entry(6, "", scroll = 0)
        self.rhevm_server_port.setCallback(self.valid_rhevm_server_port_callback)
        rhevm_grid.setField(self.rhevm_server, 1, 0, anchorLeft = 1, padding=(2, 0, 0, 1))
        rhevm_grid.setField(self.rhevm_server_port, 1, 1, anchorLeft = 1, padding=(2, 0, 0, 1))
        elements.setField(rhevm_grid, 0, 1, anchorLeft = 1, padding = (0,0,0,0))
        elements.setField(Label(""), 0, 2, anchorLeft = 1)
        self.verify_rhevm_cert = Checkbox("Connect to RHEV Manager and Validate Certificate", isOn=True)
        elements.setField(self.verify_rhevm_cert, 0, 3, anchorLeft = 1, padding = (0,0,0,0))
        elements.setField(Label(""), 0, 4, anchorLeft = 1)

        elements.setField(Label("Set RHEV-M Admin Password"), 0, 5, anchorLeft = 1)
        pw_elements = Grid(3,3)

        pw_elements.setField(Label("Password: "), 0, 1, anchorLeft = 1)
        self.root_password_1 = Entry(15, password=1)
        self.root_password_1.setCallback(self.password_check_callback)
        pw_elements.setField(self.root_password_1, 1, 1)
        pw_elements.setField(Label("Confirm Password: "), 0, 2, anchorLeft = 1)
        self.root_password_2 = Entry(15, password=1)
        self.root_password_2.setCallback(self.password_check_callback)
        pw_elements.setField(self.root_password_2, 1, 2)
        self.pw_msg = Textbox(60, 6, "", wrap=1)

        elements.setField(pw_elements, 0, 6, anchorLeft=1)
        elements.setField(self.pw_msg, 0, 7, padding = (0,0,0,0))

        inputFields = [self.rhevm_server, self.rhevm_server_port, self.verify_rhevm_cert,
                       self.root_password_1, self.root_password_2]
        if not is_network_up:
            for field in inputFields:
                field.setFlags(FLAG_DISABLED, FLAGS_SET)

        try:
            rhevm_server = get_rhevm_config()
            rhevm_server,rhevm_port = rhevm_server.split(":")
            if rhevm_server.startswith("None"):
                self.rhevm_server.set("")
            else:
                self.rhevm_server.set(rhevm_server)
            self.rhevm_server_port.set(rhevm_port)

        except:
            pass
        return [Label(""), elements]

    def password_check_callback(self):
        resp, msg = password_check(self.root_password_1.value(), self.root_password_2.value())
        self.pw_msg.setText(msg)
        return

    def action(self):
        self.ncs.screen.setColor("BUTTON", "black", "red")
        self.ncs.screen.setColor("ACTBUTTON", "blue", "white")
        if self.root_password_1.value() != "" and self.root_password_2.value() != "" and self.root_password_1.value() == self.root_password_2.value():
            set_password(self.root_password_1.value(), "root")
            augtool("set", "/files/etc/ssh/sshd_config/PasswordAuthentication", "yes")
            dn = file('/dev/null', 'w+')
            subprocess.Popen(['/sbin/service', 'sshd', 'restart'], stdout=dn, stderr=dn)
        if len(self.rhevm_server.value()) > 0:
            deployUtil.nodeCleanup()
            if self.verify_rhevm_cert.selected():
                if deployUtil.getRhevmCert(self.rhevm_server.value(),  self.rhevm_server_port.value()):
                    path, dontCare = deployUtil.certPaths('')
                    fp = deployUtil.generateFingerPrint(path)
                    approval = ButtonChoiceWindow(self.ncs.screen,
                                "Certificate Fingerprint:",
                                fp, buttons = ['Approve', 'Reject'])
                    if 'reject' == approval:
                        ButtonChoiceWindow(self.ncs.screen, "Fingerprint rejected", "RHEV-M Configuration Failed", buttons = ['Ok'])
                        return False
                    else:
                        ovirt_store_config(path)
                        self.ncs.reset_screen_colors()
                else:
                    ButtonChoiceWindow(self.ncs.screen, "RHEV-M Configuration", "Failed downloading RHEV-M certificate", buttons = ['Ok'])
                    self.ncs.reset_screen_colors()
            # Stopping vdsm-reg may fail but its ok - its in the case when the menus are run after installation
            deployUtil._logExec([constants.EXT_SERVICE, 'vdsm-reg', 'stop'])
            if write_vdsm_config(self.rhevm_server.value(), self.rhevm_server_port.value()):
                deployUtil._logExec([constants.EXT_SERVICE, 'vdsm-reg',
                    'start'])
                ButtonChoiceWindow(self.ncs.screen, "RHEV-M Configuration", "RHEV-M Configuration Successfully Updated", buttons = ['Ok'])
                self.ncs.reset_screen_colors()
                return True
            else:
                ButtonChoiceWindow(self.ncs.screen, "RHEV-M Configuration", "RHEV-M Configuration Failed", buttons = ['Ok'])
                self.ncs.reset_screen_colors()
                return False

    def valid_rhevm_server_callback(self):
        if not is_valid_host_or_ip(self.rhevm_server.value()):
            self.ncs.screen.setColor("BUTTON", "black", "red")
            self.ncs.screen.setColor("ACTBUTTON", "blue", "white")
            ButtonChoiceWindow(self.ncs.screen, "Configuration Check", "Invalid RHEV-M Hostname or Address", buttons = ['Ok'])
            self.ncs.reset_screen_colors()


    def valid_rhevm_server_port_callback(self):
        if not is_valid_port(self.rhevm_server_port.value()):
            self.ncs.screen.setColor("BUTTON", "black", "red")
            self.ncs.screen.setColor("ACTBUTTON", "blue", "white")
            ButtonChoiceWindow(self.ncs.screen, "Configuration Check", "Invalid RHEV-M Server Port", buttons = ['Ok'])
            self.ncs.reset_screen_colors()

def get_plugin(ncs):
    return Plugin(ncs)
