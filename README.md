# blepty
Create a PTY interface for an HM-1x Bluetooth LE module on Linux.

This program makes it possible to use applications which expect to
talk to a normal serial port (/dev/ttySx or /dev/ttyACMx) with
devices that use HM-1x BLE adapters.  It does this by creating
a pseudo-terminal (PTY) and forwarding data between the PTY and
the BLE adapter.

## Prerequisites

1. A Bluetooth LE adapter on the host computer.
2. A Bluetooth LE device using a JNHuaMao BLE modules.
3. A supported OS on the host computer (Linux for now)
4. The necessary Python Bluetooth and GATT suport libraries.
   (pybluez and gattlib)

## Usage

blepty.py connects to a JNHuaMao Bluetooth Low Energy module and
creates a pseudo-terminal (pty) that can be opened like a serial
port.  The program writes the path to the terminal program and then
runs in the foreground, passing data between the BLE module and
the PTY.

First, find the BLE device you wish to connect to.

    $ sudo ./blepty.py -l
    Devices
        name: TNC5 BLE, address: 00:0E:0B:03:05:FA

Then, run the program, connecting to the device's MAC address:

    $ sudo ./blepty.py -m 00:0E:0B:03:05:FA
    Listening on /dev/pts/9
    data: 00

Note that it created a PTY here at `/dev/pts/9`.  Any program that
can talk to a serial port can connect to the PTY at this path.

## Capabilities

This program must be run as root because interpreted programs
cannot have capabilities assigned to them.  If they could, then

    sudo setcap 'cap_net_raw,cap_net_admin+eip' blepty.py 

would allow this program to run without root privileges.

Another work-around is to use cython to compile the program into a
standalone executable and the apply then capabilities to that
executable.

    $ cython --embed blepty.py 
    $ make blepty CFLAGS="-I/usr/include/python2.7" LDFLAGS="-lpython2.7"
    $ sudo setcap 'cap_net_raw,cap_net_admin+eip' blepty
