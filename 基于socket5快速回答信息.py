# server.py
import socket
import struct
import json
import os
import threading
from typing import List, Dict, Set
import re

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey, X25519PublicKey
)
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.serialization import PublicFormat, Encoding

HOST = "0.0.0.0"
PORT = 9000

def derive_key(shared: bytes, info: bytes = b"mt_server_x25519") -> bytes:
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info)
    return hkdf.derive(shared)

def recv_exact(conn: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("connection closed while receiving")
        buf += chunk
    return buf

def jaccard_char_similarity(a: str, b: str) -> float:
    sa = set(a)
    sb = set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)

def simple_word_tokens(text: str) -> List[str]:
    # 基于非字母/数字/汉字的分隔，保留中文字符块与英文单词/数字
    tokens = re.findall(r'[\u4e00-\u9fff]+|[A-Za-z0-9]+', text)
    return tokens

def build_inverted_index(docs: List[Dict[str, str]], mode: str = "char") -> Dict[str, Set[str]]:
    inv = {}
    for d in docs:
        doc_id = d["id"]
        text = d.get("title", "")
        if mode == "char":
            toks = set(text)
        else:
            toks = set(simple_word_tokens(text))
        for t in toks:
            inv.setdefault(t, set()).add(doc_id)
    return inv

# Example docs
DOCUMENTS: List[Dict[str, str]] = [
    {"id": "doc1", "title": "机器学习基础", "content": "介绍监督学习、无监督学习和常用算法的入门教程。"},
    {"id": "doc2", "title": "深度学习进阶", "content": "覆盖神经网络、卷积网络和训练技巧的详尽文档。"},
    {"id": "doc3", "title": "自然语言处理概览", "content": "分词、编码、注意力机制及应用示例。"},
    {"id": "doc4", "title": "统计学习方法", "content": "统计建模、概率论基础与回归分析。"},
    {"id": "doc5", "title": "计算机视觉入门", "content": "图像处理、特征提取与目标检测简介。"},
]

# Build inverted index on titles (default char-level)
INV_INDEX = build_inverted_index(DOCUMENTS, mode="char")
DOC_MAP = {d["id"]: d for d in DOCUMENTS}

def retrieve_candidates(query: str, inv_index: Dict[str, Set[str]], mode: str = "char", candidate_limit: int = 10, use_intersection: bool = False):
    if mode == "char":
        toks = set(query)
    else:
        toks = set(simple_word_tokens(query))
    if not toks:
        return []
    sets = [inv_index.get(t, set()) for t in toks]
    if use_intersection:
        # intersection of token posting lists
        cand = set.intersection(*sets) if sets else set()
    else:
        # union
        cand = set().union(*sets)
    # limit
    cand_list = list(cand)[:candidate_limit]
    return [DOC_MAP[cid] for cid in cand_list]

def score_query_against_docs(query: str, docs: List[Dict[str, str]], title_weight: float = 0.6, content_weight: float = 0.4):
    results = []
    for d in docs:
        title_sim = jaccard_char_similarity(query, d.get("title", ""))
        content_sim = jaccard_char_similarity(query, d.get("content", ""))
        total = title_weight * title_sim + content_weight * content_sim
        results.append({
            "id": d.get("id"),
            "title": d.get("title"),
            "content": d.get("content"),
            "title_score": title_sim,
            "content_score": content_sim,
            "total_score": total
        })
    results.sort(key=lambda x: x["total_score"], reverse=True)
    return results

# --- handshake + network code same as before; handle_client uses retrieval above ---
def handle_client(conn: socket.socket, addr):
    try:
        hdr = recv_exact(conn, 1 + 32)
        if hdr[0] != 0x01:
            conn.close()
            return
        cli_pub = hdr[1:33]

        srv_priv = X25519PrivateKey.generate()
        srv_pub = srv_priv.public_key().public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
        nonce_prefix = os.urandom(12)
        conn.sendall(bytes([0x01]) + srv_pub + nonce_prefix)

        shared = srv_priv.exchange(X25519PublicKey.from_public_bytes(cli_pub))
        key = derive_key(shared)
        aead = ChaCha20Poly1305(key)

        recv_ctr = 0
        send_ctr = 0

        ln_b = recv_exact(conn, 4)
        ln = struct.unpack(">I", ln_b)[0]
        ct = recv_exact(conn, ln)

        nonce_int = int.from_bytes(nonce_prefix, "big") ^ recv_ctr
        nonce = nonce_int.to_bytes(12, "big")
        try:
            plain = aead.decrypt(nonce, ct, None)
        except Exception:
            conn.close()
            return

        obj = json.loads(plain.decode("utf-8"))
        query = obj.get("query", "")
        tw = float(obj.get("title_weight", 0.6))
        cw = float(obj.get("content_weight", 0.4))
        tokenize_mode = obj.get("tokenize_mode", "char")  # "char" or "word"
        candidate_limit = int(obj.get("candidate_limit", 10))
        use_intersection = bool(obj.get("use_intersection", False))

        # retrieve candidates from inverted index built on titles
        candidates = retrieve_candidates(query, INV_INDEX, mode=tokenize_mode, candidate_limit=candidate_limit, use_intersection=use_intersection)

        # If no candidates found, fallback to scanning all docs
        if not candidates:
            candidates = DOCUMENTS

        scored = score_query_against_docs(query, candidates, title_weight=tw, content_weight=cw)

        resp_obj = {
            "query": query,
            "tokenize_mode": tokenize_mode,
            "candidate_limit": candidate_limit,
            "use_intersection": use_intersection,
            "top_results": scored[:candidate_limit]
        }
        resp_plain = json.dumps(resp_obj, ensure_ascii=False).encode("utf-8")

        nonce_int = int.from_bytes(nonce_prefix, "big") ^ send_ctr
        nonce = nonce_int.to_bytes(12, "big")
        ct_out = aead.encrypt(nonce, resp_plain, None)
        conn.sendall(struct.pack(">I", len(ct_out)) + ct_out)

    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass

def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(5)
    print(f"listening on {HOST}:{PORT}")
    try:
        while True:
            conn, addr = srv.accept()
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()
    finally:
        srv.close()

if __name__ == "__main__":
    main()




# client.py
import socket
import struct
import json
import socks

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey, X25519PublicKey
)
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.serialization import PublicFormat, Encoding

def derive_key(shared: bytes, info: bytes = b"mt_server_x25519") -> bytes:
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info)
    return hkdf.derive(shared)

def recv_exact(s: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("connection closed while receiving")
        buf += chunk
    return buf

def socks5_query_encrypted(proxy_host, proxy_port, server_host, server_port, query,
                           title_weight: float = 0.6, content_weight: float = 0.4,
                           tokenize_mode: str = "char", candidate_limit: int = 10,
                           use_intersection: bool = False, timeout: float = 10.0):
    # create socket (via socks5 proxy if proxy_host not None)
    if proxy_host:
        s = socks.socksocket()
        s.set_proxy(socks.SOCKS5, proxy_host, proxy_port)
    else:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect((server_host, server_port))

    # handshake: send version(0x01) + client_pub (32 bytes raw)
    cli_priv = X25519PrivateKey.generate()
    cli_pub = cli_priv.public_key().public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
    s.sendall(bytes([0x01]) + cli_pub)

    # receive server response: 1 + 32 + 12
    resp = recv_exact(s, 1 + 32 + 12)
    if resp[0] != 0x01:
        s.close()
        raise RuntimeError("server did not accept encrypted handshake")
    srv_pub = resp[1:33]
    nonce_prefix = resp[33:45]

    shared = cli_priv.exchange(X25519PublicKey.from_public_bytes(srv_pub))
    key = derive_key(shared)
    aead = ChaCha20Poly1305(key)

    # build request JSON with retrieval params
    req_obj = {
        "query": query,
        "title_weight": title_weight,
        "content_weight": content_weight,
        "tokenize_mode": tokenize_mode,        # "char" or "word"
        "candidate_limit": int(candidate_limit),
        "use_intersection": bool(use_intersection)
    }
    plain = json.dumps(req_obj, ensure_ascii=False).encode("utf-8")

    # send encrypted request: 4-byte len + ciphertext (counter = 0)
    send_ctr = 0
    nonce_int = int.from_bytes(nonce_prefix, "big") ^ send_ctr
    nonce = nonce_int.to_bytes(12, "big")
    ct = aead.encrypt(nonce, plain, None)
    s.sendall(struct.pack(">I", len(ct)) + ct)

    # receive encrypted response
    ln_b = recv_exact(s, 4)
    ln = struct.unpack(">I", ln_b)[0]
    ct = recv_exact(s, ln)
    recv_ctr = 0
    nonce_int = int.from_bytes(nonce_prefix, "big") ^ recv_ctr
    nonce = nonce_int.to_bytes(12, "big")
    resp_plain = aead.decrypt(nonce, ct, None)
    s.close()
    return json.loads(resp_plain.decode("utf-8"))

if __name__ == "__main__":
    # Example usage: adjust proxy_host/proxy_port if using a proxy.
    proxy_host = "127.0.0.1"   # set to None for direct connection
    proxy_port = 1080
    server_host = "127.0.0.1"
    server_port = 9000

    query_text = "机器学习和神经网络"

    result = socks5_query_encrypted(
        proxy_host=proxy_host,
        proxy_port=proxy_port,
        server_host=server_host,
        server_port=server_port,
        query=query_text,
        title_weight=0.7,
        content_weight=0.3,
        tokenize_mode="char",
        candidate_limit=5,
        use_intersection=False
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))








# mt_server.py
import socket
import json
import threading
from typing import Dict, List, Tuple
# ------------------- 文章字典 -------------------
articles: Dict[str, Dict[str, str]] = {
    "001": {
        "title": "机器学习入门指南",
        "content": "机器学习是一门研究计算机如何通过经验自动改进的学科..."
    },
    "002": {
        "title": "深度学习与神经网络",
        "content": "深度学习是机器学习的一个分支，利用多层神经网络进行特征提取..."
    },
    "003": {
        "title": "自然语言处理技术概览",
        "content": "自然语言处理（NLP）涉及文本分析、情感识别、机器翻译等任务..."
    }
}
# ------------------------------------------------
def lcs_length(a: str, b: str) -> int:
    """动态规划求最长公共子序列长度（空间 O(min(len)))）。"""
    if len(a) < len(b):
        a, b = b, a          # 让 a 更长，节省空间
    prev = [0] * (len(b) + 1)
    for ch in a:
        cur = [0]
        for j, bj in enumerate(b, 1):
            if ch == bj:
                cur.append(prev[j - 1] + 1)
            else:
                cur.append(max(cur[-1], prev[j]))
        prev = cur
    return prev[-1]
def search_titles(query: str) -> List[Tuple[str, str, float]]:
    """
    在所有标题中搜索，返回 (title, content, score) 列表。
    score = LCS_len / len(query)
    """
    results = []
    for art in articles.values():
        title = art["title"]
        lcs_len = lcs_length(query, title)
        score = lcs_len / len(query) if query else 0
        results.append((title, art["content"], score))
    results.sort(key=lambda x: x[2], reverse=True)   # 按分数降序
    return results
def handle_client(conn: socket.socket, addr):
    """每个客户端一个线程，处理一次请求后关闭连接。"""
    try:
        raw = conn.recv(4096)
        if not raw:
            return
        request = json.loads(raw.decode())
        query = request.get("query", "")
        matches = search_titles(query)[:3]   # 只返回前 3 条
        payload = [
            {"title": t, "content": c, "score": round(s, 3)}
            for t, c, s in matches
        ]
        response = json.dumps({"query": query, "results": payload})
        conn.sendall(response.encode())
    except Exception as e:
        err = json.dumps({"error": str(e)})
        conn.sendall(err.encode())
    finally:
        conn.close()
        print(f"Closed connection from {addr}")
def start_server(host: str = "0.0.0.0", port: int = 9000):
    """主监听循环，使用 threading.Thread 为每个客户端创建新线程。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen()
        print(f"[Server] Listening on {host}:{port}")
        while True:
            conn, addr = srv.accept()
            print(f"[Server] New connection from {addr}")
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()
if __name__ == "__main__":
    start_server()







# client.py
import socket
import socks
import json
def socks5_query(proxy_host, proxy_port, server_host, server_port, query):
    s = socks.socksocket()
    s.set_proxy(socks.SOCKS5, proxy_host, proxy_port)
    s.connect((server_host, server_port))
    s.sendall(json.dumps({"query": query}).encode())
    resp = s.recv(8192)
    s.close()
    return json.loads(resp.decode())
if __name__ == "__main__":
    result = socks5_query(
        proxy_host="127.0.0.1", proxy_port=1080,
        server_host="127.0.0.1", server_port=9000,
        query="机器学习"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))

