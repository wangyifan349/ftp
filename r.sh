sudo apt update
apt install  python3-pip
pip3 install -U pip
pip3 install  pyopenssl
pip3 install pyftpdlib
nohup python3 sslftp.py >/dev/null 2>&1&
lsof -i:21
