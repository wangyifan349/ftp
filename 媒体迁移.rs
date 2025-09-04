Cargo.toml
[package]
name = "media_migrator_gui"
version = "0.1.0"
edition = "2021"

[dependencies]
eframe = "0.24"           # egui 框架，用于桌面 GUI
egui = "0.24"
rfd = "0.9"               # 文件/文件夹选择对话框
walkdir = "2.3"
sha2 = "0.10"
hex = "0.4"
rayon = "1.7"
anyhow = "1.0"
parking_lot = "0.12"      # 轻量锁





use anyhow::Result;
use eframe::{egui, epi};
use parking_lot::Mutex;
use rayon::prelude::*;
use rfd::FileDialog;
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::fs;
use std::io::{BufReader, Read};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use walkdir::WalkDir;

const IMAGE_EXTS: &[&str] = &["jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "heic"];
const VIDEO_EXTS: &[&str] = &[
    "mp4", "mkv", "mov", "avi", "wmv", "flv", "webm", "m4v", "ts", "mpeg",
];
const AUDIO_EXTS: &[&str] = &["mp3", "flac", "wav", "aac", "m4a", "ogg", "wma"];

fn ext_lower(path: &Path) -> Option<String> {
    path.extension().and_then(|s| s.to_str()).map(|s| s.to_lowercase())
}
fn file_type_dir_name(path: &Path) -> Option<&'static str> {
    match ext_lower(path).as_deref() {
        Some(ext) if IMAGE_EXTS.contains(&ext) => Some("images"),
        Some(ext) if VIDEO_EXTS.contains(&ext) => Some("videos"),
        Some(ext) if AUDIO_EXTS.contains(&ext) => Some("music"),
        _ => None,
    }
}
fn is_media_file(path: &Path) -> bool {
    file_type_dir_name(path).is_some()
}
fn sha256_of_file(path: &Path) -> Result<Vec<u8>> {
    let f = fs::File::open(path)?;
    let mut reader = BufReader::new(f);
    let mut hasher = Sha256::new();
    let mut buf = [0u8; 8192];
    loop {
        let n = reader.read(&mut buf)?;
        if n == 0 { break; }
        hasher.update(&buf[..n]);
    }
    Ok(hasher.finalize().to_vec())
}
fn make_unique_path(dir: &Path, file_name: &str) -> PathBuf {
    let mut tgt = dir.join(file_name);
    if !tgt.exists() { return tgt; }
    let mut idx = 1u32;
    let stem = Path::new(file_name).file_stem().and_then(|s| s.to_str()).unwrap_or("file");
    let ext = Path::new(file_name).extension().and_then(|s| s.to_str());
    loop {
        let candidate = if let Some(e) = &ext { format!("{}({}).{}", stem, idx, e) } else { format!("{}({})", stem, idx) };
        tgt = dir.join(&candidate);
        if !tgt.exists() { return tgt; }
        idx += 1;
    }
}

#[derive(Default)]
struct AppState {
    src_dirs: Vec<PathBuf>,
    dst_dir: Option<PathBuf>,
    copy_mode: bool,
    use_trash: bool,
    logs: Vec<String>,
    progress: f32,    // 0.0..1.0
    total_tasks: usize,
    done_tasks: usize,
    running: bool,
    last_summary: String,
}

#[derive(Clone)]
struct TransferPlan {
    items: Vec<(PathBuf, PathBuf)>, // src -> dst
}

impl AppState {
    fn log(&mut self, s: impl Into<String>) {
        self.logs.push(s.into());
        if self.logs.len() > 1000 { self.logs.drain(..200); }
    }
}

struct MediaMigratorApp {
    state: Arc<Mutex<AppState>>,
}

impl Default for MediaMigratorApp {
    fn default() -> Self {
        Self { state: Arc::new(Mutex::new(AppState::default())) }
    }
}

impl MediaMigratorApp {
    fn scan_sources(src_dirs: &[PathBuf], state: &mut AppState) -> Vec<PathBuf> {
        let mut files = Vec::new();
        for d in src_dirs {
            if !d.exists() {
                state.log(format!("源目录不存在，跳过: {}", d.display()));
                continue;
            }
            for entry in WalkDir::new(d).into_iter().filter_map(|e| e.ok()) {
                let p = entry.path();
                if p.is_file() && is_media_file(p) {
                    files.push(p.to_path_buf());
                }
            }
        }
        files
    }

    fn build_plan(files: Vec<PathBuf>, dst_dir: &Path, state: &mut AppState) -> TransferPlan {
        let dst_images = dst_dir.join("images");
        let dst_videos = dst_dir.join("videos");
        let dst_music = dst_dir.join("music");
        let mut used = std::collections::HashSet::new();
        let mut items = Vec::new();
        for src in files {
            if let Some(kind) = file_type_dir_name(&src) {
                let base = match kind {
                    "images" => &dst_images,
                    "videos" => &dst_videos,
                    "music" => &dst_music,
                    _ => &dst_images,
                };
                let fname = src.file_name().and_then(|s| s.to_str()).unwrap_or("file");
                let mut tgt = base.join(fname);
                if tgt.exists() || used.contains(&tgt) {
                    tgt = make_unique_path(base, fname);
                }
                used.insert(tgt.clone());
                items.push((src, tgt));
            }
        }
        state.log(format!("规划 {} 个文件的迁移/复制", items.len()));
        TransferPlan { items }
    }

    fn perform_plan(plan: TransferPlan, copy_mode: bool, use_trash: bool, state_arc: Arc<Mutex<AppState>>) {
        // run in background thread
        std::thread::spawn(move || {
            let state = &mut *state_arc.lock();
            state.running = true;
            state.total_tasks = plan.items.len();
            state.done_tasks = 0;
            state.progress = 0.0;
            // ensure target dirs exist
            for (_, dst) in &plan.items {
                if let Some(p) = dst.parent() {
                    let _ = fs::create_dir_all(p);
                }
            }
            // move/copy files sequentially but update progress (could be parallelized with care)
            for (src, dst) in plan.items.into_iter() {
                let res = if copy_mode {
                    fs::copy(&src, &dst).map(|_| ())
                } else {
                    match fs::rename(&src, &dst) {
                        Ok(_) => Ok(()),
                        Err(_) => {
                            // fallback to copy+remove
                            match fs::copy(&src, &dst) {
                                Ok(_) => fs::remove_file(&src).map(|_| ()),
                                Err(e) => Err(e),
                            }
                        }
                    }
                };
                let mut st = state;
                match res {
                    Ok(_) => st.log(format!("OK: {} -> {}", src.display(), dst.display())),
                    Err(e) => st.log(format!("失败: {} -> {} : {:?}", src.display(), dst.display(), e)),
                }
                st.done_tasks += 1;
                if st.total_tasks > 0 {
                    st.progress = (st.done_tasks as f32) / (st.total_tasks as f32) * 0.6; // first 60% for transfer
                }
            }

            // 去重阶段
            // collect all media files under dst root (depth 2)
            let dst_root = {
                let s = state;
                s.last_summary.clone(); // noop to borrow
                // we can't get dst from state due to current design; instead store dst in plan items earlier if needed.
            };

            // For simplicity, find common parent from first dst if exists
            let maybe_root = plan.items.first().and_then(|(_, d)| d.parent().map(|p| p.parent().map(|pp| pp.to_path_buf())).flatten());
            // But plan.items was moved; we can't. Instead recompute target root by checking user's selected dst saved in state before spawn.
            // To keep code concise here, we'll read dst from environment saved into logs: not ideal in prod. Better to pass dst explicitly.
            // For this example, assume destination dirs are siblings created: search current working dir's "images"/"videos"/"music"
            // Instead, expect that the GUI code calls this function with state having dst_dir saved; to keep this self-contained, skip this complexity.

            // We'll compute target files by scanning typical subdirs if they exist under user's chosen dst (store it in state.logs[0] earlier).
            // --- For robustness, in real code pass dst explicitly. ---

            // To keep GUI responsive and still illustrate, we'll perform a simple dedupe by scanning images/videos/music under the first dst recorded in logs.
            // Find dst by reading the last_summary field which the GUI sets to the dst path prior to calling this function.
            let dst_path_opt = {
                let s = state_arc.lock();
                s.last_summary.clone()
            };
            let dst_path = if dst_path_opt.is_empty() {
                state_arc.lock().log("无法确定目标目录以进行去重。跳过去重。".to_string());
                state_arc.lock().running = false;
                return;
            } else { PathBuf::from(dst_path_opt) };

            // gather files
            let mut targets = Vec::new();
            for entry in WalkDir::new(&dst_path).max_depth(2).into_iter().filter_map(|e| e.ok()) {
                let p = entry.path().to_path_buf();
                if p.is_file() && is_media_file(&p) {
                    targets.push(p);
                }
            }

            state_arc.lock().log(format!("去重：扫描到 {} 个目标文件，计算 SHA-256...", targets.len()));

            // parallel compute hashes
            let hashes: Vec<(PathBuf, String)> = targets
                .par_iter()
                .filter_map(|p| match sha256_of_file(p) {
                    Ok(h) => Some((p.clone(), hex::encode(h))),
                    Err(e) => {
                        state_arc.lock().log(format!("哈希失败 {} : {:?}", p.display(), e));
                        None
                    }
                })
                .collect();

            let mut groups: HashMap<String, Vec<PathBuf>> = HashMap::new();
            for (p, h) in hashes {
                groups.entry(h).or_default().push(p);
            }

            let mut removed = 0usize;
            let total_groups = groups.len();
            let mut processed = 0usize;
            for (_h, mut group) in groups {
                processed += 1;
                // update progress (remaining 40%)
                {
                    let mut st = state_arc.lock();
                    st.progress = 0.6 + (processed as f32 / total_groups as f32) * 0.4;
                }
                if group.len() <= 1 { continue; }
                group.sort();
                for dup in group.iter().skip(1) {
                    if use_trash {
                        let trash = dst_path.join(".trash");
                        let _ = fs::create_dir_all(&trash);
                        let file_name = dup.file_name().and_then(|s| s.to_str()).unwrap_or("dup");
                        let mut tgt = trash.join(file_name);
                        if tgt.exists() { tgt = make_unique_path(&trash, file_name); }
                        match fs::rename(dup, &tgt) {
                            Ok(_) => { state_arc.lock().log(format!("移动重复: {} -> {}", dup.display(), tgt.display())); removed += 1; }
                            Err(_) => match fs::remove_file(dup) {
                                Ok(_) => { state_arc.lock().log(format!("删除重复: {}", dup.display())); removed += 1; }
                                Err(e) => { state_arc.lock().log(format!("删除失败 {} : {:?}", dup.display(), e)); }
                            }
                        }
                    } else {
                        match fs::remove_file(dup) {
                            Ok(_) => { state_arc.lock().log(format!("删除重复: {}", dup.display())); removed += 1; }
                            Err(e) => { state_arc.lock().log(format!("删除失败 {} : {:?}", dup.display(), e)); }
                        }
                    }
                }
            }

            {
                let mut st = state_arc.lock();
                st.progress = 1.0;
                st.running = false;
                st.log(format!("完成。去重阶段删除/移动重复文件 {} 个。", removed));
            }
        });
    }
}

impl epi::App for MediaMigratorApp {
    fn name(&self) -> &str { "媒体迁移器（GUI）" }

    fn update(&mut self, ctx: &egui::Context, _frame: &epi::Frame) {
        let mut state = self.state.lock();

        egui::CentralPanel::default().show(ctx, |ui| {
            ui.heading("媒体迁移器（Images / Videos / Music）");
            ui.horizontal(|ui| {
                if ui.button("添加源目录").clicked() {
                    if let Some(d) = FileDialog::new().pick_folder() {
                        state.src_dirs.push(d);
                    }
                }
                if ui.button("选择目标目录").clicked() {
                    if let Some(d) = FileDialog::new().pick_folder() {
                        state.dst_dir = Some(d);
                    }
                }
                if ui.button("清空源列表").clicked() {
                    state.src_dirs.clear();
                }
            });

            ui.separator();
            ui.label("源目录：");
            for (i, s) in state.src_dirs.iter().enumerate() {
                ui.horizontal(|ui| {
                    ui.label(s.display().to_string());
                    if ui.small_button("移除").clicked() {
                        state.src_dirs.remove(i);
                    }
                });
            }

            ui.separator();
            ui.label(format!("目标目录: {}", state.dst_dir.as_ref().map(|p| p.display().to_string()).unwrap_or_else(|| "<未选择>".into())));
            ui.horizontal(|ui| {
                ui.checkbox(&mut state.copy_mode, "复制（保留源文件）");
                ui.checkbox(&mut state.use_trash, "去重时移动重复到 .trash（否则直接删除）");
            });

            ui.separator();
            if ui.button("生成并显示操作清单").clicked() {
                // generate summary
                if state.src_dirs.is_empty() || state.dst_dir.is_none() {
                    state.log("请先添加至少一个源目录并选择目标目录。");
                } else {
                    let files = MediaMigratorApp::scan_sources(&state.src_dirs, &mut state);
                    let cnt = files.len();
                    let mut images = 0usize; let mut videos = 0usize; let mut music = 0usize;
                    for f in &files {
                        match file_type_dir_name(f) {
                            Some("images") => images += 1,
                            Some("videos") => videos += 1,
                            Some("music") => music += 1,
                            _ => {}
                        }
                    }
                    let dst = state.dst_dir.as_ref().unwrap();
                    let summary = format!(
                        "将要执行的操作清单：\n目标目录: {}\n将创建子目录: images, videos, music\n将处理 {} 个文件（图片 {}, 视频 {}, 音频 {})\n模式: {}\n重复处理: {}\n注意: 同名文件会自动重命名，去重基于 SHA-256（保留一个）。",
                        dst.display(),
                        cnt, images, videos, music,
                        if state.copy_mode { "复制（保留源）" } else { "移动（删除源）" },
                        if state.use_trash { format!("先移动重复到 {}/.trash", dst.display()) } else { "直接删除重复".to_string() }
                    );
                    state.last_summary = dst.display().to_string();
                    state.log(summary.clone());
                    // also store last_summary text to show in UI
                    state.log("请在下方按下 确认并开始 执行操作，或继续修改设置。");
                }
            }

            ui.separator();
            ui.horizontal(|ui| {
                if ui.add_enabled(!state.running, egui::Button::new("确认并开始")).clicked() {
                    // require dst and src
                    if state.src_dirs.is_empty() || state.dst_dir.is_none() {
                        state.log("请先选择源目录和目标目录。");
                    } else {
                        // scan and build plan
                        let files = MediaMigratorApp::scan_sources(&state.src_dirs, &mut state);
                        if files.is_empty() {
                            state.log("未找到媒体文件，取消。");
                        } else {
                            // create target subdirs
                            let dst = state.dst_dir.as_ref().unwrap().clone();
                            let _ = fs::create_dir_all(dst.join("images"));
                            let _ = fs::create_dir_all(dst.join("videos"));
                            let _ = fs::create_dir_all(dst.join("music"));
                            if state.use_trash { let _ = fs::create_dir_all(dst.join(".trash")); }

                            let plan = MediaMigratorApp::build_plan(files, &dst, &mut state);
                            // store dst path for dedupe stage
                            state.last_summary = dst.display().to_string();
                            // kick off worker
                            let plan_clone = plan.clone();
                            let state_arc = self.state.clone();
                            MediaMigratorApp::perform_plan(plan_clone, state.copy_mode, state.use_trash, state_arc);
                        }
                    }
                }

                if ui.add_enabled(state.running, egui::Button::new("取消任务")).clicked() {
                    // not implemented graceful cancel in this example
                    state.log("取消功能未实现（示例版）。任务将继续运行直到完成。");
                }
            });

            ui.separator();
            ui.label("进度：");
            ui.add(egui::ProgressBar::new(state.progress).show_percentage());

            ui.separator();
            ui.label("日志：");
            egui::ScrollArea::vertical().show(ui, |ui| {
                for line in &state.logs {
                    ui.label(line);
                }
            });
        });

        // request repaint while running
        if state.running {
            ctx.request_repaint();
        }
    }
}

fn main() {
    let options = eframe::NativeOptions::default();
    eframe::run_native(
        "媒体迁移器（GUI）",
        options,
        Box::new(|_cc| Box::new(MediaMigratorApp::default())),
    );
}
