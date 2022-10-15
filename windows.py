from pyftpdlib.servers import FTPServer
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import TLS_FTPHandler
def main():
    authorizer = DummyAuthorizer()
    authorizer.add_user('wangyifan', 'hellowindows123', '..', perm='elradfmwMT')
    #authorizer.add_anonymous('.')
    handler = TLS_FTPHandler
    handler.encoding = 'gbk'#windows下是GBK编码的真是奇了啪.....
    handler.certfile = 'server.crt'
    handler.keyfile = 'server.key'
    handler.authorizer = authorizer
    #requires SSL for both control and data channel
    handler.tls_control_required = False
    handler.tls_data_required = False
    #windows的资源管理器实在是垃圾的FTP客户端,他不允许使用以上两个TLS功能,这会导致FTP的命令部分和传文件部分全部暴漏,很不隐私。
    #如把上面两个改成True的话,windows客户端(资源管理器)将无法工作。
    #handler.masquerade_address = '185.161.70.200'#windows资源管理器下不能开启这个!!!!!
    handler.passive_ports = range(3000,4000)
    server = FTPServer(('0.0.0.0', 21), handler)
    server.serve_forever()
if __name__ == '__main__':
    main()
