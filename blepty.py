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

BLETNC_SERVICE_UUID = '424a0001-90d6-4c48-b2aa-ab415169c333'
BLETNC_RX_CHAR_UUID = '424a0002-90d6-4c48-b2aa-ab415169c333'
BLETNC_TX_CHAR_UUID = '424a0003-90d6-4c48-b2aa-ab415169c333'

class NotifyTNC(GATTResponse):
    """
    Notifications are received here and printed to STDOUT.
    """

    def pty(self, fd):
        self.fd = fd

    def on_response(self, data):
        print("NotifyTNC data: {}".format(binascii.hexlify(data)))

class TNCRequester(GATTRequester):
    """
    The requester connected to the specific GATT characteristic.
    """

    def __init__(self, address, fd):
        self.fd = fd
        GATTRequester.__init__(self, address, False)
        self.response = NotifyTNC()
        self.response.pty(fd)
        self.connect(True, channel_type = 'random', security_level = 'medium')

        self.handle = self.find_characteristic()

        print("Reading from handle {}".format(self.handle))

        self.read_by_handle_async(self.handle, self.response)

    def find_characteristic(self):

        # Find the UART characterstic and store its handle.
        chars = self.discover_characteristics()

        handle = [x['value_handle'] for x in chars
            if x['uuid'] == BLETNC_RX_CHAR_UUID]

        if len(handle) == 0:
            raise RuntimeError("UART Characteristic not found.")

        return handle[0]

    def get_handle(self): return self.handle

    def on_notification(self, handle, data):
        print("TNCRequester data[{:2d}]: {}".format(len(data[3:]), binascii.hexlify(data[0:])))
        os.write(self.fd, data[3:])

    def __del__(self):
        self.disconnect()

class Master(object):

    def __init__(self, address):
        # Open PTY
        self.master, self.slave = pty.openpty()

        # Start reqeuster
        self.requester = TNCRequester(address, self.master)
        self.handle = self.requester.get_handle()

        # Configure slave PTY for Serial port emulation.
        tty.setraw(self.slave)
        attr = termios.tcgetattr(self.slave)
        attr[3] = attr[3] & ~termios.ECHO
        termios.tcsetattr(self.slave, termios.TCSADRAIN, attr)
        
        # PTY eeds to be accessible if running as root.
        os.fchmod(self.slave, 0666)
        
        print("Listening on {}".format(os.ttyname(self.slave)))

    def run(self):
        """Read from the master endpoint of the PTY.  Use poll() to
        wait for data.  Data that is received is sent in no more
        than 20-byte chunks.  If less than 20 bytes are read, the
        read times out after 10ms and sends the data that has
        been read."""
        
        # Set up the poll object.
        flag = fcntl.fcntl(self.master, fcntl.F_GETFD)
        fcntl.fcntl(self.master, fcntl.F_SETFD, flag | os.O_NONBLOCK)
        p = select.poll()
        p.register(self.master, select.POLLIN)
        pos = 0
        
        while True:
            if pos == 0:
                # Create a new buffer and wait for data.  This can
                # only wait a few seconds in order to check for
                # BLE disconnection.
                block = StringIO()
                poll_results = p.poll(3000)
            else:
                # We read less than 20 bytes.  Time out in 10ms to
                # send a short packet.
                poll_results = p.poll(10)
            
            if len(poll_results) == 0:
                # Poll timeout -- must be a short packet.
                if not self.requester.is_connected():
                    print("Disconnected")
                    break

                if pos == 0: continue # nothing to send

                print("write[{:2d}]: {}".format(len(block.getvalue()),
                    binascii.hexlify(block.getvalue())))
                self.requester.write_by_handle_async(self.handle,
                    str(bytearray(block.getvalue())),
                    self.requester.response)
                pos = 0
            else:
                # Read one byte at a time.  This is to ensure that
                # we do not block in the read.
                c = os.read(self.master, 1)
                block.write(c)
                pos += len(c)
            
            if pos == 20:
                print("write[{:2d}]: {}".format(len(block.getvalue()), binascii.hexlify(block.getvalue())))
                self.requester.write_by_handle_async(self.handle, block.getvalue(), self.requester.response)
                pos = 0

        print("Done.")
        sys.exit(0)

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
    service = DiscoveryService('hci0')
    return service.discover(2)

def list():
    devices = get_devices()
    print("Devices")
    for address, name in devices.items():
        print("    name: {}, address: {}".format(name, address))
        try:
            req = GATTRequester(address, False)
            req.connect(True, channel_type = 'random', security_level = 'medium')
            chars = req.discover_characteristics()
            for char in chars:
                print(char)
            req.disconnect()
        except RuntimeError, ex:
            print(str(ex))

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
        master.run()
