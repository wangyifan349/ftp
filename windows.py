
from pyftpdlib.servers import FTPServer
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import TLS_FTPHandler


def main():
    authorizer = DummyAuthorizer()
    authorizer.add_user('wangyifan', 'helloUSA', '..', perm='elradfmwMT')
    authorizer.add_user('JDOjfmweojf','fjw#Ojfma3@#l;al','/root/xhjfiles',perm='elradfmwMT')
    #authorizer.add_anonymous('.')
    handler = TLS_FTPHandler
    handler.encoding = 'gbk'
    handler.certfile = 'server.crt'
    handler.keyfile = 'server.key'
    handler.authorizer = authorizer
    #requires SSL for both control and data channel
    #handler.tls_control_required = True
    #handler.tls_data_required = True
    handler.masquerade_address = '185.161.70.200'
    handler.passive_ports = range(3000,4000)
    server = FTPServer(('0.0.0.0', 21), handler)
    server.serve_forever()

if __name__ == '__main__':
    main()
