sudo apt update
apt install  python3-pip
pip3 install -U pip
pip3 install  pyopenssl
pip3 install pyftpdlib
apt install openssl -y
openssl genrsa -out server.key 2048
openssl req -new -x509 -days 3650 -key server.key -out server.crt
nohup python3 sslftp.py >/dev/null 2>&1&
nohup python3 windows.py >/dev/null 2>&1&
lsof -i:21
lsof -i:2121
