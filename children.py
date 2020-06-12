import socket, select
import array
import sys
import multiprocessing
import os
import time
import pwd
import grp

import logging

logger = logging.getLogger()
logging.basicConfig(format='%(asctime)-15s pid=%(process)d %(side)s: %(message)s', level=logging.INFO)

EOL1 = b'\n\n'
EOL2 = b'\n\r\n'
response = b'HTTP/1.0 200 OK\r\nDate: Mon, 1 Jan 1996 01:01:01 GMT\r\n'
response += b'Content-Type: text/plain\r\nContent-Length: 13\r\n\r\n'
response += b'Hello, world!'


# Function from https://docs.python.org/3/library/socket.html#socket.socket.recvmsg
def recv_fds(sock, msglen, maxfds):
    fds = array.array("i")  # Array of ints
    msg, ancdata, flags, addr = sock.recvmsg(msglen, socket.CMSG_LEN(maxfds * fds.itemsize))
    for cmsg_level, cmsg_type, cmsg_data in ancdata:
        if (cmsg_level == socket.SOL_SOCKET and cmsg_type == socket.SCM_RIGHTS):
            # Append data, ignoring any truncated integers at the end.
            fds.fromstring(cmsg_data[:len(cmsg_data) - (len(cmsg_data) % fds.itemsize)])
    return msg, list(fds)


def new_recv_fd(socket_filename):
    try:
        os.remove("/tmp/uds_socket")
    except OSError:
        pass

    logger.info('Starting privledges: %d/%d = %s/%s' % \
                (os.getuid(),
                 os.getgid(),
                 pwd.getpwuid(os.getuid())[0],
                 grp.getgrgid(os.getgid())[0]), extra={"side": "<== RECV"})

    if os.getuid() == 0:
        running_uid = pwd.getpwnam("nobody")[2]
        running_gid = grp.getgrnam("nogroup")[2]
        os.setgid(running_gid)
        os.setuid(running_uid)

        logger.info('Dropped privledges: currently %d/%d = %s/%s' % \
                    (os.getuid(),
                     os.getgid(),
                     pwd.getpwuid(os.getuid())[0],
                     grp.getgrgid(os.getgid())[0]), extra={"side": "<== RECV"})

    logger.info("Receiver delaying creation of socket to demonstrate sender retries...", extra={"side": "<== RECV"})
    logger.info("Binding to (and creating) AF_UNIX socket socket file '%s'" % socket_filename,
                extra={"side": "<== RECV"})
    sock = socket.socket(family=socket.AF_UNIX)
    sock.bind(socket_filename)
    sock.listen()
    logger.info("Socket listening %s" % sock, extra={"side": "<== RECV"})

    # Waste a file descriptor, so the fd numbers on source and receive sides don't match (they'll be both 6 by default)
    leak_a_file_descriptor = open("/etc/hosts")

    if not hasattr(sock, "recvmsg"):
        raise RuntimeError(
            "We don't have a `Socket.recvmsg` in this implementation of python (eg, system python 2.7 on OSX")

    # Accept exactly 1 connection
    client, info = sock.accept()
    logger.info("Connected, client=%s" % client, extra={"side": "<== RECV"})

    logger.info("Blocking until message is received", extra={"side": "<== RECV"})
    msg, fds = recv_fds(client, 100, 4)
    logger.info("Received message msg=%s fds=%s" % (msg, fds), extra={"side": "<== RECV"})
    #
    # f = os.fdopen(fds[0])
    # logger.info("Opened fd %d => %s" % (fds[0], f), extra={"side": "<== RECV"})
    #
    # logger.info("Printing first 5 lines of file content", extra={"side": "<== RECV"})
    # for line, n in zip(f, range(5)):
    #     logger.info("%d ... %s" % (n, line.strip()), extra={"side": "<== RECV"})
    #
    # f.close()
    return fds[0]


if __name__ == '__main__':

    fdno = new_recv_fd("/tmp/uds_socket")
    logger.info("got from parent fd %d" % (fdno), extra={"side": "<== RECV"})
    serversocket = socket.socket(fileno=fdno)
    # serversocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # serversocket.bind(('0.0.0.0', 8080))
    # serversocket.listen(1)
    # serversocket.setblocking(True)

    epoll = select.epoll()
    epoll.register(serversocket.fileno(), select.EPOLLIN)
    try:
        connections = {}
        requests = {}
        responses = {}
        while True:
            events = epoll.poll(1)
            for fileno, event in events:
                if fileno == serversocket.fileno():
                    connection, address = serversocket.accept()
                    connection.setblocking(0)
                    epoll.register(connection.fileno(), select.EPOLLIN)
                    connections[connection.fileno()] = connection
                    requests[connection.fileno()] = b''
                    responses[connection.fileno()] = response
                elif event & select.EPOLLIN:
                    requests[fileno] += connections[fileno].recv(1024)
                    if EOL1 in requests[fileno] or EOL2 in requests[fileno]:
                        epoll.modify(fileno, select.EPOLLOUT)
                        #print('-' * 40 + '\n' + requests[fileno].decode()[:-2])
                elif event & select.EPOLLOUT:
                    byteswritten = connections[fileno].send(responses[fileno])
                    responses[fileno] = responses[fileno][byteswritten:]
                    if len(responses[fileno]) == 0:
                        epoll.modify(fileno, 0)
                        connections[fileno].shutdown(socket.SHUT_RDWR)
                elif event & select.EPOLLHUP:
                    epoll.unregister(fileno)
                    connections[fileno].close()
                    del connections[fileno]
    finally:
        epoll.unregister(serversocket.fileno())
        epoll.close()
        serversocket.close()
