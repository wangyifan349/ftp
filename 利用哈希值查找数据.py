from flask import Flask, request, jsonify
import hashlib

app = Flask(__name__)

# 内存索引：hash_hex -> list of original data (字符串或 hex 表示)
_index = {}
_HASH_ALGO = "sha256"

def compute_hash_bytes(data_bytes: bytes) -> str:
    """对二进制数据精确计算哈希，返回小写十六进制字符串。"""
    h = hashlib.new(_HASH_ALGO)
    h.update(data_bytes)
    return h.hexdigest()

@app.route("/add", methods=["POST"])
def add_data():
    """
    添加数据（用于测试）。
    - application/json: JSON {"data": "<string>"}，以 UTF-8 编码计算哈希并保存原字符串。
    - 其他: 读取原始请求体 bytes，计算哈希；如果可解码为 UTF-8 保存为字符串，否则保存为 hex。
    返回: { "hash": "<hex>" }，状态 201。
    """
    if request.is_json:
        body = request.get_json()
        if not isinstance(body, dict) or "data" not in body:
            return jsonify({"error": "missing 'data' field in JSON"}), 400
        if not isinstance(body["data"], str):
            return jsonify({"error": "'data' must be a string"}), 400
        data_bytes = body["data"].encode("utf-8")
        stored_repr = body["data"]
    else:
        data_bytes = request.get_data() or b""
        try:
            stored_repr = data_bytes.decode("utf-8")
        except Exception:
            stored_repr = data_bytes.hex()

    h = compute_hash_bytes(data_bytes)
    _index.setdefault(h, []).append(stored_repr)
    return jsonify({"hash": h}), 201

@app.route("/data/<hash_hex>", methods=["GET"])
def get_by_hash(hash_hex):
    """
    按哈希查询。返回匹配的数据列表（可能为空）。
    示例: GET /data/<sha256-hex>
    """
    expected_len = len(hashlib.new(_HASH_ALGO).hexdigest())
    if not isinstance(hash_hex, str) or len(hash_hex) != expected_len:
        return jsonify({"error": "invalid hash length"}), 400
    try:
        int(hash_hex, 16)
    except ValueError:
        return jsonify({"error": "hash must be hexadecimal"}), 400

    results = _index.get(hash_hex, [])
    return jsonify({"hash": hash_hex, "matches": results}), 200





    添加数据（JSON）：curl -X POST -H "Content-Type: application/json" -d '{"data":"hello"}' http://localhost:8000/add
    查询数据：curl http://localhost:8000/data/

