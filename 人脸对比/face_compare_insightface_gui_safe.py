#!/usr/bin/env python3
# face_compare_insightface_gui_safe.py
# Tkinter GUI for InsightFace face comparison with safer threading and conventions.
# Requirements: insightface, opencv-python, numpy
# 2025-11-09

import os
import sys
import json
import threading
import queue
import traceback
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import numpy as np
import cv2
import insightface
from insightface.app import FaceAnalysis

# ---------- Constants ----------
DEFAULT_MODEL = "antelope"
DEFAULT_THRESHOLD_COSINE = 0.45
DEFAULT_THRESHOLD_L2 = 1.0
MAX_WORKERS = 2  # thread pool size

# ---------- State container (thread-safe where needed) ----------
class AppState:
    def __init__(self):
        self.lock = threading.Lock()
        self.model_name = DEFAULT_MODEL
        self.face_app = None  # FaceAnalysis instance
        self.preparing = False
        self.last_result = None
        self.threshold_cosine = DEFAULT_THRESHOLD_COSINE
        self.threshold_l2 = DEFAULT_THRESHOLD_L2

    def set_preparing(self, val: bool):
        with self.lock:
            self.preparing = val

    def is_preparing(self) -> bool:
        with self.lock:
            return self.preparing

    def set_face_app(self, app: FaceAnalysis):
        with self.lock:
            self.face_app = app

    def get_face_app(self):
        with self.lock:
            return self.face_app

    def set_model_name(self, name: str):
        with self.lock:
            self.model_name = name

    def get_model_name(self) -> str:
        with self.lock:
            return self.model_name

    def set_last_result(self, result: dict):
        with self.lock:
            self.last_result = result

    def get_last_result(self):
        with self.lock:
            return self.last_result

    def set_thresholds(self, cosine: float, l2: float):
        with self.lock:
            self.threshold_cosine = cosine
            self.threshold_l2 = l2

    def get_thresholds(self):
        with self.lock:
            return self.threshold_cosine, self.threshold_l2

app_state = AppState()

# ---------- Worker infrastructure ----------
# Use a queue to pass messages (status updates, results, exceptions) from worker threads to main thread
MESSAGE_STATUS = "status"
MESSAGE_RESULT = "result"
MESSAGE_ERROR = "error"
MESSAGE_MODEL_READY = "model_ready"

message_queue = queue.Queue()

executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

def enqueue_message(msg_type: str, payload):
    message_queue.put((msg_type, payload))

# ---------- InsightFace helpers ----------
def prepare_face_app(model_name: str):
    """
    Prepare FaceAnalysis model. This may download model files and take time.
    Returns FaceAnalysis instance or raises Exception.
    """
    ctx_id = 0 if insightface.utils.has_cuda() else -1
    fa = FaceAnalysis(name=model_name)
    fa.prepare(ctx_id=ctx_id, det_size=(640, 640))
    return fa

def read_image_bgr(path: str):
    image = cv2.imread(path)
    if image is None:
        raise FileNotFoundError(f"无法读取图片: {path}")
    return image

# ---------- Worker tasks ----------
def task_prepare_model(model_name: str, cancel_flag: threading.Event):
    """
    Background task to prepare model. Uses cancel_flag to indicate cancellation request.
    It cannot truly cancel the internal download of insightface but can avoid overwriting state
    if cancelled.
    """
    try:
        enqueue_message(MESSAGE_STATUS, f"准备模型：{model_name}（可能需要下载，耐心等待）")
        face_app = prepare_face_app(model_name)
        if cancel_flag.is_set():
            enqueue_message(MESSAGE_STATUS, f"准备模型已取消：{model_name}")
            return  # do not set global state
        # set into global state
        app_state.set_face_app(face_app)
        app_state.set_model_name(model_name)
        enqueue_message(MESSAGE_MODEL_READY, model_name)
        enqueue_message(MESSAGE_STATUS, f"模型准备完成：{model_name}")
    except Exception as exc:
        tb = traceback.format_exc()
        enqueue_message(MESSAGE_ERROR, ("模型准备失败", str(exc), tb))

def task_compare_images(image_path_a: str, image_path_b: str, model_name: str, thresholds: tuple):
    """
    Background task to compare two images and return result dict.
    """
    try:
        enqueue_message(MESSAGE_STATUS, "读取图片...")
        img_a = read_image_bgr(image_path_a)
        img_b = read_image_bgr(image_path_b)

        enqueue_message(MESSAGE_STATUS, "检测人脸并提取特征...")
        face_app = app_state.get_face_app()
        if face_app is None or face_app.name != model_name:
            # Try to prepare model synchronously here (shouldn't happen if UI auto-prepared).
            face_app = prepare_face_app(model_name)
            app_state.set_face_app(face_app)
            app_state.set_model_name(model_name)

        faces_a = face_app.get(img_a)
        faces_b = face_app.get(img_b)
        if len(faces_a) == 0 or len(faces_b) == 0:
            raise RuntimeError("至少一张图片未检测到人脸。请确保图片有人脸且清晰。")

        emb_a = faces_a[0].embedding.astype(np.float64)
        emb_b = faces_b[0].embedding.astype(np.float64)

        l2_distance = float(np.linalg.norm(emb_a - emb_b))
        norm_a = np.linalg.norm(emb_a)
        norm_b = np.linalg.norm(emb_b)
        if norm_a == 0 or norm_b == 0:
            raise RuntimeError("embedding 为零向量，无法计算余弦相似度。")

        cosine_similarity = float(np.dot(emb_a, emb_b) / (norm_a * norm_b))
        cosine_distance = 1.0 - cosine_similarity
        threshold_cosine, threshold_l2 = thresholds
        verdicts = {
            "cosine_match": cosine_similarity >= threshold_cosine,
            "l2_match": l2_distance <= threshold_l2
        }

        result = {
            "image1": image_path_a,
            "image2": image_path_b,
            "model": model_name,
            "embedding_dim": int(len(emb_a)),
            "cosine_similarity": float(cosine_similarity),
            "cosine_distance": float(cosine_distance),
            "l2_distance": float(l2_distance),
            "thresholds": {"cosine": float(threshold_cosine), "l2": float(threshold_l2)},
            "verdicts": verdicts
        }

        app_state.set_last_result(result)
        enqueue_message(MESSAGE_RESULT, result)
        enqueue_message(MESSAGE_STATUS, "比对完成")
    except Exception as exc:
        tb = traceback.format_exc()
        enqueue_message(MESSAGE_ERROR, ("比对失败", str(exc), tb))

# ---------- Tkinter UI ----------
class FaceCompareApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("InsightFace 人脸比对（安全版）")
        self.geometry("760x560")
        self.resizable(False, False)

        # UI variables
        self.var_model = tk.StringVar(value=DEFAULT_MODEL)
        self.var_cosine = tk.DoubleVar(value=DEFAULT_THRESHOLD_COSINE)
        self.var_l2 = tk.DoubleVar(value=DEFAULT_THRESHOLD_L2)
        self.var_image_a = tk.StringVar(value="")
        self.var_image_b = tk.StringVar(value="")
        self.status_text = tk.StringVar(value="就绪")

        # Cancellation / control
        self.prepare_cancel_event = threading.Event()
        self.pending_prepare_future = None
        self.pending_compare_future = None

        self._build_ui()

        # Periodically poll message queue from worker threads
        self.after(100, self._process_message_queue)

    def _build_ui(self):
        pad = 8

        frm_model = ttk.Labelframe(self, text="模型与阈值", padding=pad)
        frm_model.place(x=10, y=10, width=740, height=120)

        ttk.Label(frm_model, text="模型:").place(x=10, y=10)
        ttk.Entry(frm_model, textvariable=self.var_model, width=22).place(x=60, y=10)
        self.btn_prepare = ttk.Button(frm_model, text="准备模型", command=self.on_prepare_model)
        self.btn_prepare.place(x=270, y=7)

        ttk.Label(frm_model, text="余弦阈值:").place(x=10, y=45)
        ttk.Entry(frm_model, textvariable=self.var_cosine, width=12).place(x=90, y=45)
        ttk.Label(frm_model, text="L2 阈值:").place(x=190, y=45)
        ttk.Entry(frm_model, textvariable=self.var_l2, width=12).place(x=240, y=45)

        frm_images = ttk.Labelframe(self, text="图片", padding=pad)
        frm_images.place(x=10, y=140, width=740, height=160)

        ttk.Label(frm_images, text="图片 A:").place(x=10, y=10)
        ttk.Entry(frm_images, textvariable=self.var_image_a, width=80).place(x=70, y=10)
        ttk.Button(frm_images, text="选择", command=self.select_image_a).place(x=620, y=7)

        ttk.Label(frm_images, text="图片 B:").place(x=10, y=50)
        ttk.Entry(frm_images, textvariable=self.var_image_b, width=80).place(x=70, y=50)
        ttk.Button(frm_images, text="选择", command=self.select_image_b).place(x=620, y=47)

        self.btn_compare = ttk.Button(frm_images, text="开始比对", command=self.on_compare)
        self.btn_compare.place(x=10, y=100)
        self.btn_save = ttk.Button(frm_images, text="保存结果为 JSON", command=self.on_save_json)
        self.btn_save.place(x=120, y=100)

        frm_result = ttk.Labelframe(self, text="比对结果", padding=pad)
        frm_result.place(x=10, y=320, width=740, height=200)

        self.txt_result = tk.Text(frm_result, wrap="word", state="disabled")
        self.txt_result.place(x=10, y=5, width=720, height=150)

        self.status_bar = ttk.Label(self, textvariable=self.status_text, relief="sunken", anchor="w")
        self.status_bar.place(x=0, y=540, width=760, height=20)

    # ---------- UI helpers ----------
    def set_status(self, message: str):
        # Always call from main thread
        self.status_text.set(message)

    def append_result_text(self, text: str):
        self.txt_result.configure(state="normal")
        self.txt_result.insert("end", text + "\n")
        self.txt_result.configure(state="disabled")
        self.txt_result.see("end")

    def clear_result_text(self):
        self.txt_result.configure(state="normal")
        self.txt_result.delete("1.0", "end")
        self.txt_result.configure(state="disabled")

    def select_image_a(self):
        path = filedialog.askopenfilename(title="选择图片 A", filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp *.webp"), ("All", "*.*")])
        if path:
            self.var_image_a.set(path)

    def select_image_b(self):
        path = filedialog.askopenfilename(title="选择图片 B", filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp *.webp"), ("All", "*.*")])
        if path:
            self.var_image_b.set(path)

    # ---------- Actions ----------
    def on_prepare_model(self):
        model_name = (self.var_model.get() or DEFAULT_MODEL).strip()
        if app_state.is_preparing():
            messagebox.showinfo("信息", "已有模型正在准备，请稍候或取消。")
            return
        # cancel previous if exists
        self.prepare_cancel_event.clear()
        app_state.set_preparing(True)
        self.set_status(f"提交准备任务：{model_name}")
        # Disable buttons to avoid concurrent starts
        self.btn_prepare.config(state="disabled")
        self.btn_compare.config(state="disabled")
        # Submit to executor
        future = executor.submit(task_prepare_model, model_name, self.prepare_cancel_event)
        self.pending_prepare_future = future

        # attach a done callback that will run in worker thread; we don't touch UI there
        def _on_done(fut):
            app_state.set_preparing(False)
            # nothing else here; messages will be enqueued by the task
        future.add_done_callback(lambda f: _on_done(f))

    def on_compare(self):
        image_a = (self.var_image_a.get() or "").strip()
        image_b = (self.var_image_b.get() or "").strip()
        if not image_a or not image_b:
            messagebox.showwarning("警告", "请先选择图片 A 与图片 B。")
            return
        if not os.path.isfile(image_a):
            messagebox.showerror("错误", f"找不到图片 A: {image_a}")
            return
        if not os.path.isfile(image_b):
            messagebox.showerror("错误", f"找不到图片 B: {image_b}")
            return

        try:
            threshold_cosine = float(self.var_cosine.get())
        except Exception:
            threshold_cosine = DEFAULT_THRESHOLD_COSINE
            self.var_cosine.set(threshold_cosine)
        try:
            threshold_l2 = float(self.var_l2.get())
        except Exception:
            threshold_l2 = DEFAULT_THRESHOLD_L2
            self.var_l2.set(threshold_l2)

        app_state.set_thresholds(threshold_cosine, threshold_l2)
        model_name = (self.var_model.get() or DEFAULT_MODEL).strip()

        # Ensure model ready (if not, prepare synchronously via executor then continue when ready)
        face_app = app_state.get_face_app()
        if face_app is None or face_app.name != model_name:
            # auto-prepare: submit prepare task and then chain compare when done
            if app_state.is_preparing():
                messagebox.showinfo("信息", "模型正在准备，稍候比对会自动执行。")
            else:
                # start prepare
                self.on_prepare_model()
            # schedule a polling that will attempt to run compare when model ready
            self.set_status("等待模型准备完成后开始比对...")
            self._poll_model_ready_then_compare(image_a, image_b, model_name, (threshold_cosine, threshold_l2))
            return

        # Submit compare task
        self._submit_compare_task(image_a, image_b, model_name, (threshold_cosine, threshold_l2))

    def _poll_model_ready_then_compare(self, image_a, image_b, model_name, thresholds):
        # check every 500ms until model ready, then submit compare
        def _checker():
            face_app = app_state.get_face_app()
            if face_app is not None and face_app.name == model_name:
                self.set_status("模型已准备，开始比对...")
                self._submit_compare_task(image_a, image_b, model_name, thresholds)
            else:
                # continue polling
                self.after(500, _checker)
        self.after(500, _checker)

    def _submit_compare_task(self, image_a, image_b, model_name, thresholds):
        if self.pending_compare_future and not self.pending_compare_future.done():
            messagebox.showinfo("信息", "已有比对任务在运行，请稍候。")
            return
        # disable UI controls that should not be used during compare
        self.btn_compare.config(state="disabled")
        self.btn_prepare.config(state="disabled")
        self.clear_result_text()
        self.set_status("提交比对任务...")
        future = executor.submit(task_compare_images, image_a, image_b, model_name, thresholds)
        self.pending_compare_future = future

        def _compare_done_callback(fut):
            # re-enable buttons in main thread via message processing
            enqueue_message(MESSAGE_STATUS, "比对任务结束")
        future.add_done_callback(lambda f: _compare_done_callback(f))

    def on_save_json(self):
        result = app_state.get_last_result()
        if not result:
            messagebox.showwarning("警告", "暂无比对结果，请先执行比对。")
            return
        path = filedialog.asksaveasfilename(title="保存 JSON 到", defaultextension=".json",
                                            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as wf:
                json.dump(result, wf, ensure_ascii=False, indent=2)
            messagebox.showinfo("信息", f"已保存到: {path}")
        except Exception as exc:
            messagebox.showerror("错误", f"保存失败: {exc}")
    # ---------- Message processing ----------
    def _process_message_queue(self):
        """
        Periodically called on the main thread to process messages posted by worker threads.
        Ensures all UI updates happen on the main thread.
        """
        try:
            while True:
                msg_type, payload = message_queue.get_nowait()
                if msg_type == MESSAGE_STATUS:
                    self.set_status(payload)
                    # Re-enable buttons if appropriate
                    if payload in ("比对完成", "比对任务结束", "已保存 JSON", "就绪"):
                        self.btn_compare.config(state="normal")
                        self.btn_prepare.config(state="normal")
                elif msg_type == MESSAGE_MODEL_READY:
                    # model name in payload
                    self.var_model.set(payload)
                    self.btn_prepare.config(state="normal")
                    self.btn_compare.config(state="normal")
                    # notify user
                    self.append_result_text(f"模型准备完成: {payload}")
                elif msg_type == MESSAGE_RESULT:
                    # payload is result dict
                    result = payload
                    self.clear_result_text()
                    self.append_result_text("--- 比对结果 ---")
                    self.append_result_text(f"模型: {result.get('model')}")
                    self.append_result_text("cosine_similarity: {:.6f}".format(result.get("cosine_similarity", 0.0)))
                    self.append_result_text("cosine_distance: {:.6f}".format(result.get("cosine_distance", 0.0)))
                    self.append_result_text("l2_distance: {:.6f}".format(result.get("l2_distance", 0.0)))
                    v = result.get("verdicts", {})
                    self.append_result_text(f"判定 -> cosine_match: {v.get('cosine_match')}, l2_match: {v.get('l2_match')}")
                    self.append_result_text("-----------------")
                    # re-enable controls
                    self.btn_compare.config(state="normal")
                    self.btn_prepare.config(state="normal")
                elif msg_type == MESSAGE_ERROR:
                    # payload: (title, message, traceback)
                    title, message, tb = payload
                    self.set_status("错误")
                    self.btn_compare.config(state="normal")
                    self.btn_prepare.config(state="normal")
                    # show error dialog with basic message; keep traceback in console
                    messagebox.showerror(title, message)
                    print("后台错误详细信息：", tb, file=sys.stderr)
                else:
                    # unknown message
                    pass
                message_queue.task_done()
        except queue.Empty:
            pass
        # schedule next poll
        self.after(100, self._process_message_queue)

def main():
    app = FaceCompareApp()
    app.mainloop()
    # shutdown executor when GUI closes
    executor.shutdown(wait=False)

if __name__ == "__main__":
    main()
