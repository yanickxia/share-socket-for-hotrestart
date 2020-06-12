import socket, select
import array
import sys
import multiprocessing
import os
import time
import pwd
import grp
import logging
import threading

logger = logging.getLogger()
logging.basicConfig(format='%(asctime)-15s pid=%(process)d %(side)s: %(message)s', level=logging.INFO)

EOL1 = b'\n\n'
EOL2 = b'\n\r\n'
response = b'HTTP/1.0 200 OK\r\nDate: Mon, 1 Jan 1996 01:01:01 GMT\r\n'
response += b'Content-Type: text/plain\r\nContent-Length: 13\r\n\r\n'
response += b'Hello, world!'

running = True
shutdonwing = False


# Function from https://docs.python.org/3/library/socket.html#socket.socket.sendmsg
def send_fds(sock, msg, fds):
    return sock.sendmsg([msg], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", fds))])


def new_send_fd(socket_filename, send_sock):
    sock = socket.socket(family=socket.AF_UNIX)

    logger.info("Connecting to socket file '%s'" % socket_filename, extra={"side": "SEND ==>"})
    e = None
    for _ in range(10):
        try:
            sock.connect(socket_filename)
            break
        except OSError as e:
            logger.error("Socket file '%s' not available yet, try %d/10 (%s)" % (socket_filename, _, e),
                         extra={"side": "SEND ==>"})
            time.sleep(0.5)
            pass
    else:  # nobreak
        raise e

    logger.info("Connected", extra={"side": "SEND ==>"})

    logger.info("Sender delaying 10s to demonstrate a blocking receiver...", extra={"side": "SEND ==>"})
    time.sleep(10)
    file_descriptor_int = send_sock.fileno()
    logger.info("Sending file descriptors %d" % file_descriptor_int, extra={"side": "SEND ==>"})
    send_fds(sock, b"some payload", [file_descriptor_int])

    global running
    running = False
    global  shutdonwing
    shutdonwing = True

def shutdonw():
    time.sleep(5)
    global shutdonwing
    shutdonwing = False

if __name__ == '__main__':
    try:
        serversocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        serversocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        serversocket.bind(('0.0.0.0', 8080))
        serversocket.listen(1)
        serversocket.setblocking(True)

        threading.Thread(target=new_send_fd, args=("/tmp/uds_socket", serversocket)).start()

        epoll = select.epoll()
        epoll.register(serversocket.fileno(), select.EPOLLIN)
        connections = {}
        requests = {}
        responses = {}
        while running:
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
        threading.Thread(target=shutdonw).start()
        while shutdonwing:
            events = epoll.poll(1)
            for fileno, event in events:
                if fileno == serversocket.fileno():
                    pass
                elif event & select.EPOLLIN:
                    requests[fileno] += connections[fileno].recv(1024)
                    if EOL1 in requests[fileno] or EOL2 in requests[fileno]:
                        epoll.modify(fileno, select.EPOLLOUT)
                        # print('-' * 40 + '\n' + requests[fileno].decode()[:-2])
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
        # serversocket.close()
    print("parent will stopping........")