#!/usr/bin/env python
"""
blepty.py connects to a JNHuaMao Bluetooth Low Energy module and
creates a pseudo-terminal (pty) that can be opened like a serial
port.  The program writes the path to the terminal program and then
runs in the background, passing data between the BLE module and
the PTY.

This program must be run as root because it seems Python programs
cannot have capabilities assigned to them.  If they could, then

    sudo setcap 'cap_net_raw,cap_net_admin+eip' blepty.py 

would allow this program to run without root privileges.

The work-around is to use cython to compile the program into a
standalone executable.

$ cython --embed blepty.py 
$ make blepty CFLAGS="-I/usr/include/python2.7" LDFLAGS="-lpython2.7"
$ sudo setcap 'cap_net_raw,cap_net_admin+eip' blepty

Prerequisites:

1. A Bluetooth LE adapter on the host computer.
2. A Bluetooth LE device using a JNHuaMao BLE modules.
3. A supported OS on the host computer (Linux, OSX)
4. The necessary Python Bluetooth and GATT suport libraries.
"""

from __future__ import print_function

from bluetooth.ble import DiscoveryService
from bluetooth.ble import GATTRequester, GATTResponse

import argparse
import logging
import binascii
import sys
import os
import pty
import tty
import termios
import fcntl
import select

from time import sleep
from cStringIO import StringIO

"""
try:
    adapter.start()
    device = adapter.connect('00:0E:0B:03:05:FA', address_type=ADDRESS_TYPE)
    for uuid in device.discover_characteristics().keys():
        print("Read UUID %s: %s" % (uuid, binascii.hexlify(device.char_read(uuid))))

    value = device.char_read('0000ffe1-0000-1000-8000-00805f9b34fb', timeout = 0)
finally:
    adapter.stop()
"""

class NotifyTNC(GATTResponse):
    def pty(self, fd):
        self.fd = fd
        
    def on_response(self, data):
        print("data: {}".format(binascii.hexlify(data)))
        
        
class TNCRequester(GATTRequester):
    def __init__(self, address, fd):
        self.fd = fd
        GATTRequester.__init__(self, address, False)
        self.response = NotifyTNC()
        self.response.pty(fd)
        self.connect(False, channel_type = 'random')
        self.read_by_handle_async(0x0012, self.response)

    def on_notification(self, handle, data):
        print("data[{:2d}]: {}".format(len(data[3:]), binascii.hexlify(data[0:])))
        os.write(self.fd, data[3:])

    def __del__(self):
        self.disconnect()

class Master(object):

    def __init__(self, address):
        self.master, self.slave = pty.openpty()
        tty.setraw(self.slave)
        attr = termios.tcgetattr(self.slave)
        attr[3] = attr[3] & ~termios.ECHO
        termios.tcsetattr(self.slave, termios.TCSADRAIN, attr)
        print("Listening on {}".format(os.ttyname(self.slave)))
        os.fchmod(self.slave, 0666)
        self.requester = TNCRequester(address, self.master)
        flag = fcntl.fcntl(self.master, fcntl.F_GETFD)
        fcntl.fcntl(self.master, fcntl.F_SETFD, flag | os.O_NONBLOCK)
        p = select.poll()
        p.register(self.master, select.POLLIN)
        pos = 0
        while True:
            if pos == 0:
                block = StringIO()
                # block.write(str(bytearray([0x12, 0xe1, 0xff])))
                poll_results = p.poll(None)
            else:
                poll_results = p.poll(10)
            
            if len(poll_results) == 0:
                for i in range(pos, 23): block.write('\0')
                print("write[{:2d}]: {}".format(len(block.getvalue()), binascii.hexlify(block.getvalue())))
                result = [0]
                while result[0] != '\x19':
                    result = self.requester.write_by_handle(0x12, block.getvalue())
                    print("result = {}".format(result))
                pos = 0
            else:
                c = os.read(self.master, 1)
                block.write(c)
                pos += len(c)
            
            if pos == 23:
                print("write[{:2d}]: {}".format(len(block.getvalue()), binascii.hexlify(block.getvalue())))
                result = [0]
                while result[0] != '\x19':
                    result = self.requester.write_by_handle(0x12, block.getvalue())
                    print("result = {}".format(result))
                pos = 0

        print("Done.")
        sys.exit(0)

    def write(self, data):
        for i in range(0, len(data), 20):
            pass

def parse_args():
    parser = argparse.ArgumentParser(description='BLE UART server.')
    parser.add_argument('-m', '--mac',
        help='the MAC address of the Bluetooth LE device')
    parser.add_argument('-n', '--name',
        help='the name of the Bluetooth LE device')
    parser.add_argument('-l', '--list', action='store_true',
        help='list the discoverable Bluetooth LE devices')

    return parser.parse_args()
    
def get_devices():
    service = DiscoveryService()
    return service.discover(2)

def list():
    devices = get_devices()
    print("Devices")
    for address, name in devices.items():
        print("    name: {}, address: {}".format(name, address))
        req = GATTRequester(address, False)
        req.connect(True, channel_type = 'random')
        chars = req.discover_characteristics()
        for char in chars:
            print(char)
        req.disconnect()

def get_device(name):
    devices = get_devices()
    matches = [(a, n) for a, n in devices.items() if n == name]
    return matches

if __name__ == '__main__':
    
    args = parse_args()

    logging.basicConfig()
    logging.getLogger('bluetooth').setLevel(logging.DEBUG)

    if args.list is True:
        list()
        sys.exit(0)

    if args.mac is None and args.name is not None:
        dev = get_device(args.name)
        if len(dev) == 0:
            print(sys.stderr, "No matching devices found.")
            sys.exit(1)
        if len(dev) > 1:
            print("Multiple matching devices found.")
            sys.exit(1)
        args.mac = dev[0][0]

    if args.mac is not None:
        master = Master(args.mac)