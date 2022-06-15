#!/usr/bin/python
# 
#  Copyright (C) 2016 Kyle Walker <walker.kyle.t@gmail.com>
#  
#  This copyrighted material is made available to anyone wishing to use,
#  modify, copy, or redistribute it subject to the terms and conditions
#  of the GNU General Public License, either version 2 of the License, or
#  (at your option) any later version
# 
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
# 
# 
#  Description:
#    On systemd-using systems, reverting to the old ethN naming convention
#    for the networking stack is difficult. Primarily in that without the
#    systemd method of naming, the remaining net_id builtin functionality
#    within udev is exceptionally weak.
#    
#    This script avoids the failures of the above udev side by simply, pre-
#    network.target, renaming all interfaces on the system to a non-ethN
#    naming convention, and then applies names based off of the contents of 
#    the ifcfg-ethN configuration files.
# 
#  Author: Kyle Walker <kwalker@redhat.com>
#
#  ChangeLog:
#   * Wed Jul 4 - Kyle Walker <kwalker@redhat.com>
#     Initial release
#
# Requires:
#     The presence of HWADDR and (DEVICE or NAME) flags within the ifcfg
#     files, found within the /etc/sysconfig/network-scripts/ifcfg-eth*
#     files.
#
# Example of usage
#
#  1 - Install and run:
#     $ ./systemd_persistent_eth -i
#

from __future__ import print_function

import os, sys, shutil, pdb
import argparse
from subprocess import Popen, PIPE
from glob import glob

version = '0.1'

INSTALL = """
[Unit]
Description=Persistently name interfaces to the ethN naming convention
Before=network.target

[Service]
Type=oneshot
ExecStart=/usr/sbin/systemd_persistent_eth.py

[Install]
WantedBy=network.target
;Alias=ethN.service
"""

parser = argparse.ArgumentParser(description='Allows network interfaces to be renamed based on the desired configuration in the ifcfg files.')
parser.add_argument('-i', '--install', action='store_true', help='Installs the script as a systemd unit that will execute prior to the network.target.')
args = parser.parse_args()

def install():
    unit_install_path = '/etc/systemd/system/systemd_persistent_eth.service'
    script_install_path = '/usr/sbin/systemd_persistent_eth.py'

    print("Copying the script from %s to %s" %(__file__, script_install_path))
    
    try:
        shutil.copy(__file__, script_install_path)
    except:
        print('Failed to copy %s to %s' %(__file__, script_install_path)) 
        return True


    print("Installing to %s" %(unit_install_path))
    
    try:
        f = open(unit_install_path, 'w')
    except:
        print('Failed to open %s - Is the script running as root?' %(unit_install_path)) 
        return True

    try:
        f.write(INSTALL)
        f.close()
    except:
        print('Failed to write to %s - No space left?' %(unit_install_path))
        f.close()
        return True

    print('Wrote the following to %s' %(unit_install_path))
    print('%s' %('-' * 50))
    print('%s' %(INSTALL))
    print('%s' %('-' * 50))


    print('Issuing a "daemon-reload" to systemd')
    systemctl_proc = Popen(['systemctl', 'daemon-reload'])

    systemctl_proc.wait()
    if systemctl_proc.returncode:
        print('Failed to issue "systemctl daemon-reload" - Will requires manual intervention - Exiting.')
        return True

    del systemctl_proc


    print('Issuing a "enable systemd_persistent_eth" to systemd')
    systemctl_proc = Popen(['systemctl', 'enable', 'systemd_persistent_eth'])

    systemctl_proc.wait()
    if systemctl_proc.returncode:
        print('Failed to issue "systemctl enable systemd_persistent_eth" - Will requires manual intervention - Exiting.')
        return True
    
    return None

def get_interface_dict():
    interfaces = {}

    ip_output = Popen(['ip', 'link', 'show'], stdout=PIPE)
    ip_output.wait()

    for idx,line in enumerate(ip_output.stdout):
        if idx > 1:            # Omits loopback entries
            split_line = [ entry.rstrip(':') for entry in line.split()]
            if not idx % 2:    # Will be lines that have a device identifier
                interface = split_line[1].strip()
                connection = None if 'LOWER_UP' not in line else True
            else:
                hwaddr = split_line[1].upper().strip()
                print("%15s: %s%s" %(interface, hwaddr, '' if not connection else ' - UP'))
                interfaces[interface] = hwaddr,connection,interface

    return interfaces

def link_name_change(idx, entry, dest=None):
    ip_proc = Popen(['ip', 'link', 'set', 'dev', entry, 'down'])
    ip_proc.wait()

    del ip_proc

    if not dest:
        ip_proc = Popen(['ip', 'link', 'set', 'dev', entry, 'name', 'temp%d' %(idx)])
    else:
        ip_proc = Popen(['ip', 'link', 'set', 'dev', entry, 'name', dest])
    ip_proc.wait()

    del ip_proc

    ip_proc = Popen(['ip', 'link', 'set', 'dev', 'temp%d' %(idx), "up"])
    ip_proc.wait()

    del ip_proc

def get_config_files():
    files = {}

    filelist = glob('/etc/sysconfig/network-scripts/ifcfg-eth*')
    
    for entry in filelist:
        if ':' in entry:
            continue            #VLAN file, disregard

        f = open(entry, 'r')
        files[entry] = f.read()
        f.close()

    return files

def parse_config(string_input):
    config_dict = {}

    for line in string_input.split('\n'):
        split_line = line.split('=')
        if len(split_line) > 1:
            config_dict[split_line[0].upper().strip()] = split_line[1].upper().strip()

    return config_dict

def get_config():
    parsed_entries = {}

    cached_configs = get_config_files()
    
    for entry in cached_configs.keys():
        parsed_entries[entry] = parse_config(cached_configs[entry])

    return parsed_entries

def assign_interface(interface, configs):
    named = 0

    for entry in configs.keys():
        if configs[entry]['HWADDR'].strip('"') in interface[0]:
            if 'DEVICE' in configs[entry].keys():
                link_name_change(0, interface[2], configs[entry]['DEVICE'].lower().strip('"'))
                named += 1
            elif 'NAME' in configs[entry].keys():
                link_name_change(0, interface[2], configs[entry]['NAME'].lower().strip('"'))
                named += 1

    return named

def main():
    print('Gathering previous name association')

    interfaces = get_interface_dict()
    for idx, entry in enumerate(interfaces.keys()):
        link_name_change(idx, entry)

    print('Renamed all interfaces to temporary device names.')
    interfaces = get_interface_dict()

    print('Loading configuration files in /etc/sysconfig/network-scripts/')
    configs = get_config()

    print('Applying names from HWADDR flags in configuration files')
    for interface_entry in interfaces.keys():
        success = assign_interface(interfaces[interface_entry], configs)

    unnamed = len(interfaces.keys()) - success
    print('%d Assigned, %d Unnamed:' %(success, unnamed))
    interfaces = get_interface_dict()

    if unnamed:
        print('Renaming the devices not found in the ifcfg-ethN files to an arbitrary ethN designation')
        idx = 0
        for interface_entry in interfaces.keys():
            if 'eth' not in interfaces[interface_entry][2]:
                tempname = 'eth%d' %(idx)
                while tempname in interfaces.keys():
                    idx += 1
                    tempname = 'eth%d' %(idx)

                link_name_change(0, interface_entry, tempname)
                idx += 1

    print('Final naming scheme')
    temp = get_interface_dict()
    

if __name__ == '__main__':
    print('version: %s' % version)

    ret = None

    if args.install:
        ret = install()

    if ret:
        print('Failed to install. Exiting...')
    else:
        main()
