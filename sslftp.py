#!/usr/bin/python3
from pyftpdlib.servers import FTPServer
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import TLS_FTPHandler
def main():
    authorizer = DummyAuthorizer()
    authorizer.add_user('username', 'password', '..', perm='elradfmwMT')
    #authorizer.add_anonymous('.')
    handler = TLS_FTPHandler
    handler.certfile = '/usr/local/etc/xray/fullchain.pem'
    handler.keyfile = '/usr/local/etc/xray/privkey.pem'
    handler.authorizer = authorizer
    #requires SSL for both control and data channel
    handler.tls_control_required = True
    handler.tls_data_required = True
    handler.masquerade_address = '185.161.70.200'
    handler.passive_ports = range(1000,2500)
    server = FTPServer(('0.0.0.0', 2121), handler)
    server.serve_forever()
if __name__ == '__main__':
    main()
