//! File Organizer — Rust + GTK4
//!
//! 功能：扫描并计算 SHA256 哈希以发现重复文件，迁移按类型分类文件，按日期或扩展名整理文件。
//! GUI：基于 GTK4，暗色主题，包含三个主要面板：Scan & Dedupe, Migrate, Organize。
//!
//! 架构要点：
//! - 主线程运行 GTK；耗时操作在 std::thread::spawn 中执行，并通过 glib 主上下文回调更新 UI。
//! - 使用 sha2 计算 SHA256（纯 Rust，实现稳定，无额外系统依赖）。
//! - 使用 globset 支持排除模式（支持基于文件名或路径的通配）。
//! - 保持命名规范、完整注释、可读性优先。



[package]
name = "file_organizer_rust"
version = "0.1.0"
edition = "2021"

[dependencies]
# GTK4 bindings and GLib
gtk4 = { version = "0.6", package = "gtk4" }
glib = "0.15"
gio = "0.15"

# File traversal and patterns
walkdir = "2.3"
globset = "0.4"

# Hashing (pure Rust)
sha2 = "0.10"

# Parallelism and threading
rayon = "1.7"

# File operations
fs_extra = "1.2"

# Utils
chrono = { version = "0.4", features = ["local-offset"] }
anyhow = "1.0"






use gtk4::prelude::*;
use gtk4::{
    Application, ApplicationWindow, Button, Entry, Label, TextView, ScrolledWindow,
    ProgressBar, CheckButton, ComboBoxText, Box as GtkBox, Orientation, CssProvider,
    StyleContext,
};
use std::collections::HashMap;
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::thread;

use chrono::Local;
use fs_extra::file::{move_file, CopyOptions};
use globset::{GlobBuilder, GlobSet, GlobSetBuilder};
use sha2::{Digest, Sha256};
use walkdir::WalkDir;

const BUFFER_SIZE: usize = 65536;

/// Default type patterns used for classification.
fn default_type_patterns() -> HashMap<&'static str, Vec<&'static str>> {
    let mut map = HashMap::new();
    map.insert(
        "images",
        vec![
            "*.jpg", "*.jpeg", "*.png", "*.gif", "*.bmp", "*.tiff", "*.webp", "*.heic",
        ],
    );
    map.insert(
        "videos",
        vec!["*.mp4", "*.mkv", "*.avi", "*.mov", "*.wmv", "*.flv"],
    );
    map.insert(
        "music",
        vec!["*.mp3", "*.wav", "*.flac", "*.aac", "*.ogg", "*.m4a"],
    );
    map.insert(
        "documents",
        vec![
            "*.pdf", "*.doc", "*.docx", "*.xls", "*.xlsx", "*.ppt", "*.pptx", "*.txt", "*.md",
        ],
    );
    map
}

/// Compute SHA256 for a file at given path. Returns hex string on success, None on failure.
fn compute_sha256_file(path: &Path) -> Option<String> {
    let mut file = fs::File::open(path).ok()?;
    let mut hasher = Sha256::new();
    let mut buffer = vec![0u8; BUFFER_SIZE];
    loop {
        match file.read(&mut buffer) {
            Ok(0) => break,
            Ok(n) => hasher.update(&buffer[..n]),
            Err(_) => return None,
        }
    }
    Some(format!("{:x}", hasher.finalize()))
}

/// Build a GlobSet from patterns (supports path or filename patterns).
fn build_exclude_globset(patterns: &[String]) -> GlobSet {
    let mut builder = GlobSetBuilder::new();
    for pattern in patterns {
        if let Ok(glob) = GlobBuilder::new(pattern).literal_separator(false).build() {
            builder.add(glob);
        }
    }
    builder.build().unwrap_or_else(|_| GlobSet::empty())
}

/// Determine whether filename matches a classification key using type patterns.
fn matches_type(filename: &str, key: &str, type_patterns: &HashMap<&'static str, Vec<&'static str>>) -> bool {
    if let Some(patterns) = type_patterns.get(key) {
        let name_lc = filename.to_lowercase();
        for pat in patterns {
            if let Ok(glob) = GlobBuilder::new(pat).literal_separator(false).build() {
                let matcher = glob.compile_matcher();
                if matcher.is_match(&name_lc) {
                    return true;
                }
            }
        }
    }
    false
}

/// Create a unique path by appending " (n)" before extension when target exists.
fn unique_destination_path(path: &Path) -> PathBuf {
    if !path.exists() {
        return path.to_path_buf();
    }
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    let stem = path.file_stem().and_then(|s| s.to_str()).unwrap_or("file");
    let extension = path.extension().and_then(|e| e.to_str()).unwrap_or("");
    let mut index = 1u32;
    loop {
        let candidate = if extension.is_empty() {
            parent.join(format!("{} ({})", stem, index))
        } else {
            parent.join(format!("{} ({}) .{}", stem, index, extension).replace(" .", "."))
        };
        if !candidate.exists() {
            return candidate;
        }
        index += 1;
    }
}

/// Append log line to TextView safely from any thread.
fn append_log_safe(text_view: &TextView, message: &str) {
    let buffer = text_view.buffer();
    let timestamp = Local::now().format("%H:%M:%S").to_string();
    let line = format!("{}  {}\n", timestamp, message);
    // schedule on main context
    let buffer_clone = buffer.clone();
    glib::MainContext::default().spawn_local(async move {
        buffer_clone.insert(&mut buffer_clone.end_iter(), &line);
    });
}

/// Apply dark CSS for a nicer visual appearance.
fn apply_dark_css() {
    let css = r#"
    * { background-color: #141414; color: #E6E6E6; font-family: "Segoe UI", "Helvetica Neue", Arial; }
    window { background-color: #141414; }
    headerbar, box { background-color: transparent; }
    button { background-color: #2a2a2a; border-radius: 6px; padding: 6px 10px; border: 1px solid #333; }
    entry, textview { background-color: #0f0f0f; border: 1px solid #333; border-radius: 6px; color: #ddd; }
    progressbar { background-color: #111; border-radius: 6px; }
    label { color: #cccccc; }
    checkbutton { color: #ddd; }
    comboboxtext { background-color: #0f0f0f; color: #ddd; border: 1px solid #333; border-radius: 6px; }
    "#;

    let provider = CssProvider::new();
    provider.load_from_data(css.as_bytes());
    StyleContext::add_provider_for_display(
        &gdk::Display::default().expect("No display available"),
        &provider,
        gtk4::STYLE_PROVIDER_PRIORITY_APPLICATION,
    );
}

fn main() {
    // Create GTK application
    let application = Application::builder()
        .application_id("org.example.fileorganizer")
        .build();

    application.connect_activate(build_main_window);
    application.run();
}

fn build_main_window(app: &Application) {
    apply_dark_css();

    // Window
    let window = ApplicationWindow::builder()
        .application(app)
        .title("File Organizer — Dark")
        .default_width(1000)
        .default_height(700)
        .build();

    // Vertical container
    let main_container = GtkBox::new(Orientation::Vertical, 8);

    // ----- Scan & Dedupe UI -----
    let label_scan = Label::new(Some("Scan directory:"));
    let entry_scan = Entry::new();
    let button_browse_scan = Button::with_label("Browse");
    let button_start_scan = Button::with_label("Start Scan");
    let button_delete_duplicates = Button::with_label("Delete Duplicates");
    let combo_keep = ComboBoxText::new();
    combo_keep.append_text("first");
    combo_keep.append_text("newest");
    combo_keep.append_text("oldest");
    combo_keep.set_active(Some(0));
    let entry_exclude = Entry::new();
    entry_exclude.set_placeholder_text(Some("Exclude patterns; separated by ; e.g. *.tmp;*/node_modules/*"));
    let progress_scan = ProgressBar::new();
    let scrolled_scan = ScrolledWindow::new();
    let textview_scan = TextView::new();
    textview_scan.set_editable(false);
    scrolled_scan.set_child(Some(&textview_scan));

    // Layout for scan controls
    let scan_top = GtkBox::new(Orientation::Horizontal, 6);
    scan_top.append(&label_scan);
    scan_top.append(&entry_scan);
    scan_top.append(&button_browse_scan);
    scan_top.append(&button_start_scan);
    scan_top.append(&button_delete_duplicates);

    let scan_options = GtkBox::new(Orientation::Horizontal, 6);
    scan_options.append(&Label::new(Some("Keep:")));
    scan_options.append(&combo_keep);
    scan_options.append(&Label::new(Some("Exclude:")));
    scan_options.append(&entry_exclude);

    main_container.append(&scan_top);
    main_container.append(&scan_options);
    main_container.append(&progress_scan);
    main_container.append(&scrolled_scan);

    // ----- Migrate UI -----
    let label_source = Label::new(Some("Source:"));
    let entry_source = Entry::new();
    let button_browse_source = Button::with_label("Browse");
    let label_target = Label::new(Some("Target:"));
    let entry_target = Entry::new();
    let button_browse_target = Button::with_label("Browse");

    let check_images = CheckButton::with_label("Images");
    check_images.set_active(true);
    let check_videos = CheckButton::with_label("Videos");
    check_videos.set_active(true);
    let check_music = CheckButton::with_label("Music");
    check_music.set_active(true);
    let check_documents = CheckButton::with_label("Documents");
    check_documents.set_active(true);

    let combo_migrate_conflict = ComboBoxText::new();
    combo_migrate_conflict.append_text("rename");
    combo_migrate_conflict.append_text("overwrite");
    combo_migrate_conflict.append_text("skip");
    combo_migrate_conflict.set_active(Some(0));

    let progress_migrate = ProgressBar::new();
    let scrolled_migrate = ScrolledWindow::new();
    let textview_migrate = TextView::new();
    textview_migrate.set_editable(false);
    scrolled_migrate.set_child(Some(&textview_migrate));
    let button_start_migrate = Button::with_label("Start Migrate");

    let migrate_row1 = GtkBox::new(Orientation::Horizontal, 6);
    migrate_row1.append(&label_source);
    migrate_row1.append(&entry_source);
    migrate_row1.append(&button_browse_source);

    let migrate_row2 = GtkBox::new(Orientation::Horizontal, 6);
    migrate_row2.append(&label_target);
    migrate_row2.append(&entry_target);
    migrate_row2.append(&button_browse_target);

    let migrate_types = GtkBox::new(Orientation::Horizontal, 6);
    migrate_types.append(&check_images);
    migrate_types.append(&check_videos);
    migrate_types.append(&check_music);
    migrate_types.append(&check_documents);
    migrate_types.append(&Label::new(Some("Conflict:")));
    migrate_types.append(&combo_migrate_conflict);

    main_container.append(&migrate_row1);
    main_container.append(&migrate_row2);
    main_container.append(&migrate_types);
    main_container.append(&progress_migrate);
    main_container.append(&scrolled_migrate);
    main_container.append(&button_start_migrate);

    // ----- Organize UI -----
    let label_organize = Label::new(Some("Directory:"));
    let entry_organize = Entry::new();
    let button_browse_organize = Button::with_label("Browse");
    let combo_mode = ComboBoxText::new();
    combo_mode.append_text("by_date");
    combo_mode.append_text("by_ext");
    combo_mode.set_active(Some(0));
    let combo_conflict = ComboBoxText::new();
    combo_conflict.append_text("rename");
    combo_conflict.append_text("overwrite");
    combo_conflict.append_text("skip");
    combo_conflict.set_active(Some(0));
    let progress_organize = ProgressBar::new();
    let scrolled_organize = ScrolledWindow::new();
    let textview_organize = TextView::new();
    textview_organize.set_editable(false);
    scrolled_organize.set_child(Some(&textview_organize));
    let button_start_organize = Button::with_label("Start Organize");

    let organize_row = GtkBox::new(Orientation::Horizontal, 6);
    organize_row.append(&label_organize);
    organize_row.append(&entry_organize);
    organize_row.append(&button_browse_organize);

    let organize_options = GtkBox::new(Orientation::Horizontal, 6);
    organize_options.append(&Label::new(Some("Mode:")));
    organize_options.append(&combo_mode);
    organize_options.append(&Label::new(Some("Conflict:")));
    organize_options.append(&combo_conflict);

    main_container.append(&organize_row);
    main_container.append(&organize_options);
    main_container.append(&progress_organize);
    main_container.append(&scrolled_organize);
    main_container.append(&button_start_organize);

    window.set_child(Some(&main_container));

    // Shared state: last computed hashes
    let shared_hashes: Arc<Mutex<HashMap<String, Vec<PathBuf>>>> =
        Arc::new(Mutex::new(HashMap::new()));
    let type_patterns = Arc::new(default_type_patterns());

    // ----- Browse button handlers -----
    let window_clone = window.clone();
    button_browse_scan.connect_clicked(move |_| {
        let dialog = gtk4::FileChooserDialog::new(
            Some("Select Scan Directory"),
            Some(&window_clone),
            gtk4::FileChooserAction::SelectFolder,
        );
        dialog.add_buttons(&[("Select", gtk4::ResponseType::Ok), ("Cancel", gtk4::ResponseType::Cancel)]);
        if dialog.run() == gtk4::ResponseType::Ok {
            if let Some(file) = dialog.file() {
                if let Some(path) = file.path() {
                    entry_scan.set_text(path.to_string_lossy().as_ref());
                }
            }
        }
        dialog.close();
    });

    let window_clone = window.clone();
    button_browse_source.connect_clicked(move |_| {
        let dialog = gtk4::FileChooserDialog::new(
            Some("Select Source Directory"),
            Some(&window_clone),
            gtk4::FileChooserAction::SelectFolder,
        );
        dialog.add_buttons(&[("Select", gtk4::ResponseType::Ok), ("Cancel", gtk4::ResponseType::Cancel)]);
        if dialog.run() == gtk4::ResponseType::Ok {
            if let Some(file) = dialog.file() {
                if let Some(path) = file.path() {
                    entry_source.set_text(path.to_string_lossy().as_ref());
                }
            }
        }
        dialog.close();
    });

    let window_clone = window.clone();
    button_browse_target.connect_clicked(move |_| {
        let dialog = gtk4::FileChooserDialog::new(
            Some("Select Target Directory"),
            Some(&window_clone),
            gtk4::FileChooserAction::SelectFolder,
        );
        dialog.add_buttons(&[("Select", gtk4::ResponseType::Ok), ("Cancel", gtk4::ResponseType::Cancel)]);
        if dialog.run() == gtk4::ResponseType::Ok {
            if let Some(file) = dialog.file() {
                if let Some(path) = file.path() {
                    entry_target.set_text(path.to_string_lossy().as_ref());
                }
            }
        }
        dialog.close();
    });

    let window_clone = window.clone();
    button_browse_organize.connect_clicked(move |_| {
        let dialog = gtk4::FileChooserDialog::new(
            Some("Select Directory"),
            Some(&window_clone),
            gtk4::FileChooserAction::SelectFolder,
        );
        dialog.add_buttons(&[("Select", gtk4::ResponseType::Ok), ("Cancel", gtk4::ResponseType::Cancel)]);
        if dialog.run() == gtk4::ResponseType::Ok {
            if let Some(file) = dialog.file() {
                if let Some(path) = file.path() {
                    entry_organize.set_text(path.to_string_lossy().as_ref());
                }
            }
        }
        dialog.close();
    });

    // ----- Action: Start Scan -----
    let textview_scan_clone = textview_scan.clone();
    let progress_scan_clone = progress_scan.clone();
    let entry_exclude_clone = entry_exclude.clone();
    let shared_hashes_scan = shared_hashes.clone();

    button_start_scan.connect_clicked(move |_| {
        let root = entry_scan.text().to_string();
        if root.is_empty() || !Path::new(&root).is_dir() {
            append_log_safe(&textview_scan_clone, "Please select a valid scan directory.");
            return;
        }
        let exclude_raw = entry_exclude_clone.text().to_string();
        let exclude_patterns: Vec<String> = exclude_raw
            .split(';')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect();

        append_log_safe(&textview_scan_clone, "Start scanning...");
        progress_scan_clone.set_fraction(0.0);

        let tv = textview_scan_clone.clone();
        let progress = progress_scan_clone.clone();
        let root_path = root.clone();
        let globset = build_exclude_globset(&exclude_patterns);
        let shared_hashes_thread = shared_hashes_scan.clone();

        thread::spawn(move || {
            // Collect files
            let mut file_list: Vec<PathBuf> = Vec::new();
            for entry in WalkDir::new(&root_path).follow_links(false).into_iter().filter_map(|e| e.ok()) {
                if entry.file_type().is_file() {
                    let path = entry.path().to_path_buf();
                    if globset.is_match(&path) || globset.is_match(path.file_name().unwrap_or_default()) {
                        continue;
                    }
                    file_list.push(path);
                }
            }
            let total = file_list.len();
            if total == 0 {
                append_log_safe(&tv, "No files found to scan.");
                glib::MainContext::default().spawn_local(async move {
                    progress.set_fraction(1.0);
                });
                return;
            }
            let mut map: HashMap<String, Vec<PathBuf>> = HashMap::new();
            for (index, file_path) in file_list.iter().enumerate() {
                append_log_safe(&tv, &format!("Hashing: {}", file_path.display()));
                if let Some(hash) = compute_sha256_file(file_path) {
                    map.entry(hash).or_default().push(file_path.clone());
                } else {
                    append_log_safe(&tv, &format!("Unable to read: {}", file_path.display()));
                }
                let frac = (index + 1) as f64 / total as f64;
                let progress_clone = progress.clone();
                glib::MainContext::default().spawn_local(async move {
                    progress_clone.set_fraction(frac);
                });
            }
            // Save results to shared state
            if let Ok(mut guard) = shared_hashes_thread.lock() {
                *guard = map.clone();
            }
            let duplicate_groups = map.iter().filter(|(_, v)| v.len() > 1).count();
            let duplicate_files: usize = map.iter().filter(|(_, v)| v.len() > 1).map(|(_, v)| v.len() - 1).sum();
            append_log_safe(&tv, &format!("Scan finished: {} unique hashes, {} duplicate groups, {} duplicate files.", map.len(), duplicate_groups, duplicate_files));
            glib::MainContext::default().spawn_local(async move {
                progress.set_fraction(1.0);
            });
        });
    });

    // ----- Action: Delete Duplicates -----
    let textview_scan_clone2 = textview_scan.clone();
    let combo_keep_clone = combo_keep.clone();
    let shared_hashes_delete = shared_hashes.clone();

    button_delete_duplicates.connect_clicked(move |_| {
        let keep_strategy = combo_keep_clone.active_text().map(|s| s.to_string()).unwrap_or_else(|| "first".to_string());
        append_log_safe(&textview_scan_clone2, "Start deleting duplicates...");
        let tv = textview_scan_clone2.clone();
        let shared = shared_hashes_delete.clone();

        thread::spawn(move || {
            let map = {
                if let Ok(guard) = shared.lock() {
                    guard.clone()
                } else {
                    HashMap::new()
                }
            };
            let duplicate_groups: Vec<_> = map.into_iter().filter(|(_, v)| v.len() > 1).collect();
            if duplicate_groups.is_empty() {
                append_log_safe(&tv, "No duplicates found.");
                return;
            }
            let total_groups = duplicate_groups.len();
            let mut deleted_count = 0usize;
            for (group_index, (_hash, mut paths)) in duplicate_groups.into_iter().enumerate() {
                // Determine keeper according to strategy
                let keeper_path = match keep_strategy.as_str() {
                    "newest" => {
                        paths.sort_by_key(|p| fs::metadata(p).and_then(|m| m.modified()).ok());
                        paths.last().cloned().unwrap()
                    }
                    "oldest" => {
                        paths.sort_by_key(|p| fs::metadata(p).and_then(|m| m.modified()).ok());
                        paths.first().cloned().unwrap()
                    }
                    _ => paths[0].clone(),
                };
                for path in paths.into_iter() {
                    if path == keeper_path {
                        continue;
                    }
                    match fs::remove_file(&path) {
                        Ok(_) => {
                            deleted_count += 1;
                            append_log_safe(&tv, &format!("Deleted: {}", path.display()));
                        }
                        Err(e) => {
                            append_log_safe(&tv, &format!("Failed to delete {}: {}", path.display(), e));
                        }
                    }
                }
                // (Optional) update progress UI per group
                let frac = (group_index + 1) as f64 / total_groups as f64;
                let tv_clone = tv.clone();
                glib::MainContext::default().spawn_local(async move {
                    // intentionally not binding to a visible progressbar for delete
                    let _ = tv_clone; // keep clone alive
                    let _ = frac;
                });
            }
            append_log_safe(&tv, &format!("Delete completed. Deleted {} files.", deleted_count));
        });
    });

    // ----- Action: Start Migrate -----
    let textview_migrate_clone = textview_migrate.clone();
    let progress_migrate_clone = progress_migrate.clone();
    let entry_exclude_migrate = entry_exclude.clone();
    let type_patterns_migrate = type_patterns.clone();

    button_start_migrate.connect_clicked(move |_| {
        let source_dir = entry_source.text().to_string();
        let target_dir = entry_target.text().to_string();
        if source_dir.is_empty() || !Path::new(&source_dir).is_dir() {
            append_log_safe(&textview_migrate_clone, "Please select a valid source directory.");
            return;
        }
        if target_dir.is_empty() {
            append_log_safe(&textview_migrate_clone, "Please select a target directory.");
            return;
        }

        let mut type_keys: Vec<String> = Vec::new();
        if check_images.is_active() { type_keys.push("images".to_string()); }
        if check_videos.is_active() { type_keys.push("videos".to_string()); }
        if check_music.is_active() { type_keys.push("music".to_string()); }
        if check_documents.is_active() { type_keys.push("documents".to_string()); }

        let conflict_strategy = combo_migrate_conflict.active_text().map(|s| s.to_string()).unwrap_or_else(|| "rename".to_string());
        let exclude_raw = entry_exclude_migrate.text().to_string();
        let exclude_patterns: Vec<String> = exclude_raw
            .split(';')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect();

        append_log_safe(&textview_migrate_clone, "Start migrating...");
        progress_migrate_clone.set_fraction(0.0);

        let tv = textview_migrate_clone.clone();
        let progress = progress_migrate_clone.clone();
        let src = source_dir.clone();
        let dst = target_dir.clone();
        let keys = type_keys.clone();
        let conflict = conflict_strategy.clone();
        let globset = build_exclude_globset(&exclude_patterns);
        let type_patterns = type_patterns_migrate.clone();

        thread::spawn(move || {
            if let Err(e) = fs::create_dir_all(&dst) {
                append_log_safe(&tv, &format!("Failed to create target directory: {}", e));
                return;
            }
            // Collect files
            let mut file_list: Vec<PathBuf> = Vec::new();
            for entry in WalkDir::new(&src).into_iter().filter_map(|e| e.ok()) {
                if entry.file_type().is_file() {
                    let path = entry.path().to_path_buf();
                    if globset.is_match(&path) || globset.is_match(path.file_name().unwrap_or_default()) {
                        continue;
                    }
                    file_list.push(path);
                }
            }
            let total = file_list.len();
            if total == 0 {
                append_log_safe(&tv, "No files to migrate.");
                glib::MainContext::default().spawn_local(async move {
                    progress.set_fraction(1.0);
                });
                return;
            }
            let mut moved_count = 0usize;
            for (index, file_path) in file_list.into_iter().enumerate() {
                let file_name = file_path.file_name().and_then(|s| s.to_str()).unwrap_or_default().to_string();
                let mut moved_flag = false;
                for key in &keys {
                    if matches_type(&file_name, key, &type_patterns) {
                        let target_subdir = Path::new(&dst).join(key);
                        let _ = fs::create_dir_all(&target_subdir);
                        let mut destination = target_subdir.join(&file_name);
                        if destination.exists() {
                            match conflict.as_str() {
                                "skip" => {
                                    append_log_safe(&tv, &format!("Exists, skip: {}", destination.display()));
                                    moved_flag = true;
                                    break;
                                }
                                "overwrite" => {
                                    let _ = fs::remove_file(&destination);
                                }
                                _ => {
                                    destination = unique_destination_path(&destination);
                                }
                            }
                        }
                        let copy_options = CopyOptions::new();
                        match move_file(&file_path, &destination, &copy_options) {
                            Ok(_) => {
                                moved_count += 1;
                                append_log_safe(&tv, &format!("Moved: {} -> {}", file_path.display(), destination.display()));
                            }
                            Err(e) => {
                                append_log_safe(&tv, &format!("Move failed {}: {}", file_path.display(), e));
                            }
                        }
                        moved_flag = true;
                        break;
                    }
                }
                if !moved_flag {
                    // Move to 'others'
                    let target_subdir = Path::new(&dst).join("others");
                    let _ = fs::create_dir_all(&target_subdir);
                    let mut destination = target_subdir.join(&file_name);
                    if destination.exists() {
                        match conflict.as_str() {
                            "skip" => {
                                append_log_safe(&tv, &format!("Exists, skip: {}", destination.display()));
                            }
                            "overwrite" => {
                                let _ = fs::remove_file(&destination);
                                let copy_options = CopyOptions::new();
                                match move_file(&file_path, &destination, &copy_options) {
                                    Ok(_) => {
                                        moved_count += 1;
                                        append_log_safe(&tv, &format!("Moved: {} -> {}", file_path.display(), destination.display()));
                                    }
                                    Err(e) => {
                                        append_log_safe(&tv, &format!("Move failed {}: {}", file_path.display(), e));
                                    }
                                }
                            }
                            _ => {
                                let new_dest = unique_destination_path(&destination);
                                let copy_options = CopyOptions::new();
                                match move_file(&file_path, &new_dest, &copy_options) {
                                    Ok(_) => {
                                        moved_count += 1;
                                        append_log_safe(&tv, &format!("Moved: {} -> {}", file_path.display(), new_dest.display()));
                                    }
                                    Err(e) => {
                                        append_log_safe(&tv, &format!("Move failed {}: {}", file_path.display(), e));
                                    }
                                }
                            }
                        }
                    } else {
                        let copy_options = CopyOptions::new();
                        match move_file(&file_path, &destination, &copy_options) {
                            Ok(_) => {
                                moved_count += 1;
                                append_log_safe(&tv, &format!("Moved: {} -> {}", file_path.display(), destination.display()));
                            }
                            Err(e) => {
                                append_log_safe(&tv, &format!("Move failed {}: {}", file_path.display(), e));
                            }
                        }
                    }
                }
                // Update progress
                let frac = (index + 1) as f64 / total as f64;
                let progress_clone = progress.clone();
                glib::MainContext::default().spawn_local(async move {
                    progress_clone.set_fraction(frac);
                });
            }
            append_log_safe(&tv, &format!("Migrate completed. Moved {} files.", moved_count));
            glib::MainContext::default().spawn_local(async move {
                progress.set_fraction(1.0);
            });
        });
    });

    // ----- Action: Start Organize -----
    let textview_organize_clone = textview_organize.clone();
    let progress_organize_clone = progress_organize.clone();
    let combo_mode_clone = combo_mode.clone();
    let combo_conflict_clone = combo_conflict.clone();
    let entry_exclude_organize = entry_exclude.clone();
    let type_patterns_organize = type_patterns.clone();

    button_start_organize.connect_clicked(move |_| {
        let root_dir = entry_organize.text().to_string();
        if root_dir.is_empty() || !Path::new(&root_dir).is_dir() {
            append_log_safe(&textview_organize_clone, "Please select a valid directory to organize.");
            return;
        }
        let mode = combo_mode_clone.active_text().map(|s| s.to_string()).unwrap_or_else(|| "by_date".to_string());
        let conflict = combo_conflict_clone.active_text().map(|s| s.to_string()).unwrap_or_else(|| "rename".to_string());
        let exclude_raw = entry_exclude_organize.text().to_string();
        let exclude_patterns: Vec<String> = exclude_raw
            .split(';')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect();

        append_log_safe(&textview_organize_clone, "Start organizing...");
        progress_organize_clone.set_fraction(0.0);

        let tv = textview_organize_clone.clone();
        let progress = progress_organize_clone.clone();
        let root = root_dir.clone();
        let globset = build_exclude_globset(&exclude_patterns);
        let conflict_strategy = conflict.clone();
        let mode_strategy = mode.clone();

        thread::spawn(move || {
            // Collect files
            let mut file_list: Vec<PathBuf> = Vec::new();
            for entry in WalkDir::new(&root).into_iter().filter_map(|e| e.ok()) {
                if entry.file_type().is_file() {
                    let path = entry.path().to_path_buf();
                    if globset.is_match(&path) || globset.is_match(path.file_name().unwrap_or_default()) {
                        continue;
                    }
                    file_list.push(path);
                }
            }
            let total = file_list.len();
            if total == 0 {
                append_log_safe(&tv, "No files to organize.");
                glib::MainContext::default().spawn_local(async move {
                    progress.set_fraction(1.0);
                });
                return;
            }
            let mut moved_count = 0usize;
            for (index, file_path) in file_list.into_iter().enumerate() {
                let file_name = file_path.file_name().and_then(|s| s.to_str()).unwrap_or_default().to_string();
                // Determine destination folder
                let subfolder = if mode_strategy == "by_date" {
                    match fs::metadata(&file_path).and_then(|m| m.modified()) {
                        Ok(mod_time) => {
                            // Convert std::time::SystemTime to chrono::DateTime<Local>
                            let datetime: chrono::DateTime<Local> = mod_time.into();
                            format!("{}-{:02}", datetime.year(), datetime.month())
                        }
                        Err(_) => "unknown_date".to_string(),
                    }
                } else {
                    let ext = Path::new(&file_name).extension().and_then(|s| s.to_str()).unwrap_or("").to_lowercase();
                    if ext.is_empty() {
                        "no_ext".to_string()
                    } else {
                        ext
                    }
                };
                let destination_dir = Path::new(&root).join(subfolder);
                let _ = fs::create_dir_all(&destination_dir);
                let mut destination = destination_dir.join(&file_name);
                if destination.exists() {
                    match conflict_strategy.as_str() {
                        "skip" => {
                            append_log_safe(&tv, &format!("Exists, skip: {}", destination.display()));
                        }
                        "overwrite" => {
                            let _ = fs::remove_file(&destination);
                            let copy_options = CopyOptions::new();
                            match move_file(&file_path, &destination, &copy_options) {
                                Ok(_) => {
                                    moved_count += 1;
                                    append_log_safe(&tv, &format!("Moved (overwrite): {} -> {}", file_path.display(), destination.display()));
                                }
                                Err(e) => {
                                    append_log_safe(&tv, &format!("Move failed {}: {}", file_path.display(), e));
                                }
                            }
                        }
                        _ => {
                            let new_destination = unique_destination_path(&destination);
                            let copy_options = CopyOptions::new();
                            match move_file(&file_path, &new_destination, &copy_options) {
                                Ok(_) => {
                                    moved_count += 1;
                                    append_log_safe(&tv, &format!("Moved (rename): {} -> {}", file_path.display(), new_destination.display()));
                                }
                                Err(e) => {
                                    append_log_safe(&tv, &format!("Move failed {}: {}", file_path.display(), e));
                                }
                            }
                        }
                    }
                } else {
                    let copy_options = CopyOptions::new();
                    match move_file(&file_path, &destination, &copy_options) {
                        Ok(_) => {
                            moved_count += 1;
                            append_log_safe(&tv, &format!("Moved: {} -> {}", file_path.display(), destination.display()));
                        }
                        Err(e) => {
                            append_log_safe(&tv, &format!("Move failed {}: {}", file_path.display(), e));
                        }
                    }
                }
                // Update progress
                let frac = (index + 1) as f64 / total as f64;
                let progress_clone = progress.clone();
                glib::MainContext::default().spawn_local(async move {
                    progress_clone.set_fraction(frac);
                });
            }
            append_log_safe(&tv, &format!("Organize completed. Moved {} files.", moved_count));
            glib::MainContext::default().spawn_local(async move {
                progress.set_fraction(1.0);
            });
        });
    });

    window.present();
}
