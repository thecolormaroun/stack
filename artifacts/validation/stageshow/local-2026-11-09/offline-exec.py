#!/usr/bin/env python3
"""Inherited unprivileged seccomp: only UNIX/netlink sockets, never IP sockets."""
import ctypes
import errno
import os
import platform
import sys

if platform.machine() != 'aarch64':
    raise SystemExit('offline filter supports only reviewed Linux aarch64')

class Filter(ctypes.Structure):
    _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte),
                ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint)]

class Program(ctypes.Structure):
    _fields_ = [('len', ctypes.c_ushort), ('filter', ctypes.POINTER(Filter))]

# Audit architecture check; socket syscall=198; domain is argument zero.
# Every newly created socket must be AF_UNIX or AF_NETLINK. No IP sockets are
# inherited from this fresh SSH command. NNP prevents exec privilege gains.
raw = [(0x20, 0, 0, 4), (0x15, 1, 0, 0xc00000b7),
       (0x06, 0, 0, 0x80000000), (0x20, 0, 0, 0),
       (0x15, 0, 1, 425), (0x06, 0, 0, 0x00050000 | errno.EPERM),
       (0x15, 0, 5, 198), (0x20, 0, 0, 16),
       (0x15, 3, 0, 1), (0x15, 2, 0, 16),
       (0x06, 0, 0, 0x00050000 | errno.EPERM),
       (0x06, 0, 0, 0x80000000), (0x06, 0, 0, 0x7fff0000)]
filters = (Filter * len(raw))(*(Filter(*v) for v in raw))
program = Program(len(raw), filters)
libc = ctypes.CDLL(None, use_errno=True)
# No inherited IP socket may bypass the socket-creation rule. SSH gives this
# command only pipes for stdio; close every other inherited descriptor.
for fd in range(3):
    if os.readlink('/proc/self/fd/' + str(fd)).startswith('socket:'):
        raise SystemExit('refusing inherited socket on stdio')
os.closerange(3, 65536)
for args in [(38, 1, 0, 0, 0), (22, 2, ctypes.byref(program), 0, 0)]:
    if libc.prctl(*args):
        raise OSError(ctypes.get_errno(), 'offline seccomp enforcement failed')
os.execvp(sys.argv[1], sys.argv[1:])
