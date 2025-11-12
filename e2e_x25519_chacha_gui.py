# e2e_x25519_chacha_gui.py
# Single-file GUI demo: X25519 key exchange + ChaCha20-Poly1305 AEAD
# - Menu selects Server or Client
# - Separate threads for listening/accepting (server), connecting (client),
#   and separate threads for reading and writing on the socket to avoid UI blocking
# - Per-message random 12-byte nonce included with each frame (nonce || ciphertext)
# - Variable names use full English words, no nested functions for clarity
# Dependencies: cryptography
# Install: pip install cryptography

import socket
import struct
import threading
import tkinter as tk
from tkinter import scrolledtext, messagebox
import queue
import secrets
import sys
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 5555

# ---- Framed message helpers ----
def receive_exact(stream_socket, length):
    buffer_bytes = b''
    while len(buffer_bytes) < length:
        chunk = stream_socket.recv(length - len(buffer_bytes))
        if not chunk:
            raise ConnectionError("Connection closed")
        buffer_bytes += chunk
    return buffer_bytes

def receive_frame(stream_socket):
    header = receive_exact(stream_socket, 4)
    (payload_length,) = struct.unpack('>I', header)
    return receive_exact(stream_socket, payload_length)

def send_frame(stream_socket, payload_bytes):
    header = struct.pack('>I', len(payload_bytes))
    stream_socket.sendall(header + payload_bytes)

# ---- Key derivation ----
def derive_symmetric_key(shared_secret, info_bytes=b'X25519-ChaCha20Poly1305-v1'):
    hkdf_instance = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=info_bytes,
    )
    return hkdf_instance.derive(shared_secret)

# ---- Threads: reader and writer ----
def reader_thread_function(socket_object, aead_cipher_object, gui_queue, stop_event):
    try:
        while not stop_event.is_set():
            try:
                framed_bytes = receive_frame(socket_object)
            except ConnectionError:
                gui_queue.put(('log', "[info] connection closed by peer"))
                break
            except Exception as exc:
                gui_queue.put(('log', f"[error] receive failed: {exc}"))
                break
            if not framed_bytes:
                continue
            if len(framed_bytes) < 12:
                gui_queue.put(('log', "[error] malformed frame received"))
                continue
            message_nonce = framed_bytes[:12]
            ciphertext_bytes = framed_bytes[12:]
            try:
                plaintext_bytes = aead_cipher_object.decrypt(message_nonce, ciphertext_bytes, associated_data=None)
            except Exception as exc:
                gui_queue.put(('log', f"[error] decryption failed: {exc}"))
                continue
            try:
                message_text = plaintext_bytes.decode('utf-8', errors='replace')
            except Exception:
                message_text = repr(plaintext_bytes)
            gui_queue.put(('message', message_text))
    finally:
        stop_event.set()
        gui_queue.put(('stopped', None))

def writer_thread_function(socket_object, aead_cipher_object, send_queue, stop_event, gui_queue):
    try:
        while not stop_event.is_set():
            try:
                message_bytes = send_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if message_bytes is None:
                break
            message_nonce = secrets.token_bytes(12)
            try:
                ciphertext_bytes = aead_cipher_object.encrypt(message_nonce, message_bytes, associated_data=None)
            except Exception as exc:
                gui_queue.put(('log', f"[error] encryption failed: {exc}"))
                stop_event.set()
                break
            framed_bytes = message_nonce + ciphertext_bytes
            try:
                send_frame(socket_object, framed_bytes)
            except Exception as exc:
                gui_queue.put(('log', f"[error] send failed: {exc}"))
                stop_event.set()
                break
    finally:
        stop_event.set()
        gui_queue.put(('stopped', None))

# ---- Server accept thread ----
def server_accept_thread(listen_socket, gui_queue, stop_event, connection_ready_event, server_state):
    try:
        listen_socket.settimeout(0.5)
        while not stop_event.is_set():
            try:
                client_socket, client_address = listen_socket.accept()
            except socket.timeout:
                continue
            except Exception as exc:
                gui_queue.put(('log', f"[error] accept failed: {exc}"))
                break
            gui_queue.put(('log', f"[info] accepted connection from {client_address}"))
            server_state['connection_socket'] = client_socket
            connection_ready_event.set()
            break
    finally:
        stop_event.set()
        gui_queue.put(('stopped', None))

# ---- GUI application class (no nested functions) ----
class E2EApplication:
    def __init__(self, root_window):
        self.root = root_window
        self.root.title("X25519 + ChaCha20-Poly1305 - E2E Demo")

        self.role_variable = tk.StringVar(value='server')
        role_frame = tk.Frame(self.root)
        tk.Radiobutton(role_frame, text="Server", variable=self.role_variable, value='server').pack(side=tk.LEFT)
        tk.Radiobutton(role_frame, text="Client", variable=self.role_variable, value='client').pack(side=tk.LEFT)
        role_frame.pack(padx=6, pady=6)

        host_frame = tk.Frame(self.root)
        tk.Label(host_frame, text="Host:").pack(side=tk.LEFT)
        self.entry_host = tk.Entry(host_frame)
        self.entry_host.insert(0, DEFAULT_HOST)
        self.entry_host.pack(side=tk.LEFT)
        tk.Label(host_frame, text="Port:").pack(side=tk.LEFT)
        self.entry_port = tk.Entry(host_frame, width=6)
        self.entry_port.insert(0, str(DEFAULT_PORT))
        self.entry_port.pack(side=tk.LEFT)
        host_frame.pack(padx=6, pady=6)

        control_frame = tk.Frame(self.root)
        self.button_start = tk.Button(control_frame, text="Start", command=self.start_action)
        self.button_start.pack(side=tk.LEFT, padx=4)
        self.button_stop = tk.Button(control_frame, text="Stop", command=self.stop_action, state=tk.DISABLED)
        self.button_stop.pack(side=tk.LEFT, padx=4)
        control_frame.pack(padx=6, pady=6)

        self.text_area = scrolledtext.ScrolledText(self.root, state='normal', width=72, height=20)
        self.text_area.pack(padx=6, pady=6)

        send_frame = tk.Frame(self.root)
        self.entry_message = tk.Entry(send_frame, width=56)
        self.entry_message.pack(side=tk.LEFT, padx=4)
        self.button_send = tk.Button(send_frame, text="Send", command=self.send_action, state=tk.DISABLED)
        self.button_send.pack(side=tk.LEFT)
        send_frame.pack(padx=6, pady=6)

        # state variables
        self.listen_socket = None
        self.connection_socket = None
        self.server_accept_thread = None
        self.server_accept_stop = threading.Event()
        self.connection_ready_event = threading.Event()
        self.reader_thread = None
        self.writer_thread = None
        self.io_stop_event = threading.Event()
        self.send_queue = queue.Queue()
        self.gui_queue = queue.Queue()
        self.aead_cipher = None
        self.server_state = {}

        # schedule GUI queue processing
        self.root.after(100, self.process_gui_queue)

    def log(self, text):
        self.text_area.insert(tk.END, text + "\n")
        self.text_area.see(tk.END)

    def start_action(self):
        role = self.role_variable.get()
        host = self.entry_host.get().strip()
        try:
            port = int(self.entry_port.get().strip())
        except ValueError:
            messagebox.showerror("Error", "Invalid port")
            return
        self.button_start.config(state=tk.DISABLED)
        self.button_stop.config(state=tk.NORMAL)
        self.button_send.config(state=tk.DISABLED)
        self.text_area.delete(1.0, tk.END)
        self.log(f"[info] starting as {role} on {host}:{port}")
        if role == 'server':
            threading.Thread(target=self.start_server, args=(host, port), daemon=True).start()
        else:
            threading.Thread(target=self.start_client, args=(host, port), daemon=True).start()

    def stop_action(self):
        self.log("[info] stopping...")
        # stop accept thread if present
        if self.server_accept_thread and self.server_accept_thread.is_alive():
            self.server_accept_stop.set()
        # stop IO threads
        self.io_stop_event.set()
        # close sockets
        if self.connection_socket:
            try:
                self.connection_socket.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self.connection_socket.close()
            except Exception:
                pass
            self.connection_socket = None
        if self.listen_socket:
            try:
                self.listen_socket.close()
            except Exception:
                pass
            self.listen_socket = None
        # wake writer to exit
        try:
            self.send_queue.put(None)
        except Exception:
            pass
        self.button_start.config(state=tk.NORMAL)
        self.button_stop.config(state=tk.DISABLED)
        self.button_send.config(state=tk.DISABLED)
        self.log("[info] stopped")

    def start_server(self, bind_host, bind_port):
        # prepare listening socket
        listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listen_socket.bind((bind_host, bind_port))
            listen_socket.listen(1)
        except Exception as exc:
            self.gui_queue.put(('log', f"[error] listen failed: {exc}"))
            self.gui_queue.put(('stopped', None))
            return
        self.listen_socket = listen_socket
        self.server_accept_stop.clear()
        self.server_state = {}
        threading.Thread(target=server_accept_thread, args=(listen_socket, self.gui_queue, self.server_accept_stop, self.connection_ready_event, self.server_state), daemon=True).start()
        self.gui_queue.put(('log', f"[info] server listening on {bind_host}:{bind_port}"))
        # wait for connection or stop
        while not self.server_accept_stop.is_set() and not self.connection_ready_event.wait(timeout=0.1):
            continue
        if self.server_accept_stop.is_set():
            return
        client_socket = self.server_state.get('connection_socket')
        if not client_socket:
            self.gui_queue.put(('log', "[error] no connection socket"))
            return
        self.connection_socket = client_socket
        # perform handshake: server generates ephemeral keypair and exchanges raw public keys
        try:
            server_private_key = x25519.X25519PrivateKey.generate()
            server_public_bytes = server_private_key.public_key().public_bytes()
            client_public_bytes = receive_frame(client_socket)
            if len(client_public_bytes) != 32:
                self.gui_queue.put(('log', "[error] invalid client public key length"))
                return
            send_frame(client_socket, server_public_bytes)
            client_public_key = x25519.X25519PublicKey.from_public_bytes(client_public_bytes)
            shared_secret = server_private_key.exchange(client_public_key)
            symmetric_key = derive_symmetric_key(shared_secret)
            self.aead_cipher = ChaCha20Poly1305(symmetric_key)
        except Exception as exc:
            self.gui_queue.put(('log', f"[error] handshake failed: {exc}"))
            try:
                client_socket.close()
            except Exception:
                pass
            return
        # start IO threads
        self.io_stop_event.clear()
        self.reader_thread = threading.Thread(target=reader_thread_function, args=(client_socket, self.aead_cipher, self.gui_queue, self.io_stop_event), daemon=True)
        self.writer_thread = threading.Thread(target=writer_thread_function, args=(client_socket, self.aead_cipher, self.send_queue, self.io_stop_event, self.gui_queue), daemon=True)
        self.reader_thread.start()
        self.writer_thread.start()
        self.gui_queue.put(('log', "[info] handshake complete (server). Secure channel ready"))
        self.gui_queue.put(('ready', None))
        # wait for IO stop
        while not self.io_stop_event.is_set():
            threading.Event().wait(0.1)
        # cleanup
        try:
            client_socket.close()
        except Exception:
            pass
        try:
            listen_socket.close()
        except Exception:
            pass
        self.listen_socket = None
        self.connection_socket = None
        self.gui_queue.put(('log', "[info] server session ended"))
        self.gui_queue.put(('stopped', None))

    def start_client(self, server_host, server_port):
        try:
            connection_socket = socket.create_connection((server_host, server_port), timeout=5.0)
        except Exception as exc:
            self.gui_queue.put(('log', f"[error] connect failed: {exc}"))
            self.gui_queue.put(('stopped', None))
            return
        self.connection_socket = connection_socket
        self.gui_queue.put(('log', f"[info] connected to {server_host}:{server_port}"))
        # client handshake: send client pubkey, receive server pubkey
        try:
            client_private_key = x25519.X25519PrivateKey.generate()
            client_public_bytes = client_private_key.public_key().public_bytes()
            send_frame(connection_socket, client_public_bytes)
            server_public_bytes = receive_frame(connection_socket)
            if len(server_public_bytes) != 32:
                self.gui_queue.put(('log', "[error] invalid server public key length"))
                try:
                    connection_socket.close()
                except Exception:
                    pass
                self.gui_queue.put(('stopped', None))
                return
            server_public_key = x25519.X25519PublicKey.from_public_bytes(server_public_bytes)
            shared_secret = client_private_key.exchange(server_public_key)
            symmetric_key = derive_symmetric_key(shared_secret)
            self.aead_cipher = ChaCha20Poly1305(symmetric_key)
        except Exception as exc:
            self.gui_queue.put(('log', f"[error] handshake failed: {exc}"))
            try:
                connection_socket.close()
            except Exception:
                pass
            self.gui_queue.put(('stopped', None))
            return
        # start IO threads
        self.io_stop_event.clear()
        self.reader_thread = threading.Thread(target=reader_thread_function, args=(connection_socket, self.aead_cipher, self.gui_queue, self.io_stop_event), daemon=True)
        self.writer_thread = threading.Thread(target=writer_thread_function, args=(connection_socket, self.aead_cipher, self.send_queue, self.io_stop_event, self.gui_queue), daemon=True)
        self.reader_thread.start()
        self.writer_thread.start()
        self.gui_queue.put(('log', "[info] handshake complete (client). Secure channel ready"))
        self.gui_queue.put(('ready', None))
        while not self.io_stop_event.is_set():
            threading.Event().wait(0.1)
        try:
            connection_socket.close()
        except Exception:
            pass
        self.connection_socket = None
        self.gui_queue.put(('log', "[info] client session ended"))
        self.gui_queue.put(('stopped', None))

    def send_action(self):
        text = self.entry_message.get().strip()
        if not text:
            return
        if not self.aead_cipher:
            self.log("[error] secure channel not established")
            return
        self.entry_message.delete(0, tk.END)
        self.log(f"You: {text}")
        try:
            self.send_queue.put(text.encode('utf-8'))
        except Exception as exc:
            self.log(f"[error] failed to queue message: {exc}")

    def process_gui_queue(self):
        try:
            while True:
                item = self.gui_queue.get_nowait()
                tag, payload = item
                if tag == 'log':
                    self.log(payload)
                elif tag == 'message':
                    self.log(f"Peer: {payload}")
                elif tag == 'ready':
                    self.button_send.config(state=tk.NORMAL)
                elif tag == 'stopped':
                    # when stopped: ensure UI buttons correct
                    self.button_start.config(state=tk.NORMAL)
                    self.button_stop.config(state=tk.DISABLED)
                    self.button_send.config(state=tk.DISABLED)
                else:
                    self.log(f"[debug] unknown gui message: {tag} {payload}")
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.process_gui_queue)

# ---- main ----
def main():
    root = tk.Tk()
    app = E2EApplication(root)
    def on_close():
        app.stop_action()
        root.destroy()
        sys.exit(0)
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()

if __name__ == '__main__':
    main()
