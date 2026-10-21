"""A small SMTP server for the tests: plain (no TLS), AUTH PLAIN / LOGIN with
one user and password, AUTH XOAUTH2 with one token. Keeps what it receives."""
import base64
import email
import socketserver
import threading
from email import policy


class Server:
    def __init__(self, user="report@aequm.test", password="secret", token="tok-123"):
        self.user, self.password, self.token = user, password, token
        self.messages, self.logins = [], []
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            def say(self, line):
                self.wfile.write((line + "\r\n").encode())

            def handle(self):
                self.say("220 fake ESMTP")
                authed, rcpt, sender = False, [], None
                while True:
                    raw = self.rfile.readline()
                    if not raw:
                        return
                    line = raw.decode().rstrip("\r\n")
                    cmd = line.split(" ", 1)[0].upper()
                    if cmd in ("EHLO", "HELO"):
                        self.wfile.write(b"250-fake\r\n250-AUTH PLAIN LOGIN XOAUTH2\r\n250 SIZE 52428800\r\n")
                    elif cmd == "AUTH":
                        parts = line.split(" ")
                        mech = parts[1].upper()
                        if mech == "PLAIN":
                            data = parts[2] if len(parts) > 2 else None
                            if data is None:
                                self.say("334 ")
                                data = self.rfile.readline().decode().strip()
                            _, u, p = base64.b64decode(data).decode().split("\x00")
                            ok = (u, p) == (outer.user, outer.password)
                        elif mech == "LOGIN":
                            self.say("334 VXNlcm5hbWU6")
                            u = base64.b64decode(self.rfile.readline().strip()).decode()
                            self.say("334 UGFzc3dvcmQ6")
                            p = base64.b64decode(self.rfile.readline().strip()).decode()
                            ok = (u, p) == (outer.user, outer.password)
                        elif mech == "XOAUTH2":
                            data = parts[2] if len(parts) > 2 else None
                            if data is None:
                                self.say("334 ")
                                data = self.rfile.readline().decode().strip()
                            s = base64.b64decode(data).decode()
                            ok = s == f"user={outer.user}\x01auth=Bearer {outer.token}\x01\x01"
                            u = s
                        else:
                            ok, u = False, mech
                        outer.logins.append((mech, ok))
                        if ok:
                            authed = True
                            self.say("235 2.7.0 Authentication successful")
                        else:
                            self.say("535 5.7.3 Authentication unsuccessful")
                    elif cmd == "MAIL":
                        if not authed:
                            self.say("530 5.7.57 Client not authenticated")
                            continue
                        sender, rcpt = line[10:].strip("<> "), []
                        self.say("250 OK")
                    elif cmd == "RCPT":
                        rcpt.append(line[8:].strip("<> "))
                        self.say("250 OK")
                    elif cmd == "DATA":
                        self.say("354 go ahead")
                        buf = []
                        while True:
                            l = self.rfile.readline()
                            if l in (b".\r\n", b".\n"):
                                break
                            buf.append(l[1:] if l.startswith(b"..") else l)
                        msg = email.message_from_bytes(b"".join(buf), policy=policy.default)
                        outer.messages.append((sender, list(rcpt), msg))
                        self.say("250 2.0.0 queued as 1")
                    elif cmd == "NOOP":
                        self.say("250 OK")
                    elif cmd == "RSET":
                        self.say("250 OK")
                    elif cmd == "QUIT":
                        self.say("221 bye")
                        return
                    else:
                        self.say("502 not here")

        class TCP(socketserver.ThreadingMixIn, socketserver.TCPServer):
            allow_reuse_address = True
            daemon_threads = True
        self.tcp = TCP(("127.0.0.1", 0), Handler)
        self.port = self.tcp.server_address[1]
        threading.Thread(target=self.tcp.serve_forever, daemon=True).start()

    def close(self):
        self.tcp.shutdown()
        self.tcp.server_close()
