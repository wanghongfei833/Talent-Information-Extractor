#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人才信息管理系统 - Flask Web 应用
功能：用户管理、权限控制、API 配置
"""
import json
import re
import sys
import time
import os
import unicodedata
from typing import Optional
import glob
import io
import zipfile
from PIL import Image
from flask import Flask, Blueprint, render_template, redirect, url_for, flash, request, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from utils import merge_llm_post


def _review_file_in_user_dir(user_folder, filename):
    """确保复核相关文件路径落在用户上传目录内（防路径穿越）。"""
    if not filename or '..' in filename:
        return None
    if '/' in filename or '\\' in filename:
        return None
    full = os.path.join(user_folder, filename)
    try:
        full_r = os.path.realpath(full)
        user_r = os.path.realpath(user_folder)
        if os.path.commonpath([full_r, user_r]) != user_r:
            return None
    except ValueError:
        return None
    return full


def _json_basename_ok(filename):
    """标注 JSON 文件名基本校验（允许中文等 Unicode，禁止路径）。"""
    if not filename or not filename.endswith('.json'):
        return False
    if '..' in filename or '/' in filename or '\\' in filename:
        return False
    return os.path.basename(filename) == filename


# Windows 保留设备名（仅主文件名，不含扩展名时也要避免）
_WIN_RESERVED_NAMES = frozenset(
    ['CON', 'PRN', 'AUX', 'NUL']
    + [f'COM{i}' for i in range(1, 10)]
    + [f'LPT{i}' for i in range(1, 10)]
)


def _safe_upload_basename_unicode(original: str, max_len: int = 200) -> Optional[str]:
    """
    从浏览器传来的原始文件名得到可安全保存的「仅 basename」，保留中文等 Unicode。
    去掉路径成分、控制字符与跨平台非法字符；与 secure_filename 不同，不会整段清空中文名。
    """
    if not original or not isinstance(original, str):
        return None
    s = original.replace('\\', '/').strip()
    if not s or s.endswith('/'):
        return None
    parts = [p for p in s.split('/') if p != '']
    if not parts:
        return None
    if any(p == '..' for p in parts[:-1]):
        return None
    name = parts[-1]
    if name in ('.', '..') or '..' in name or '\x00' in name:
        return None

    forbidden = set('<>:"/\\|?*')
    out_chars = []
    for ch in unicodedata.normalize('NFC', name):
        o = ord(ch)
        if o < 32:
            continue
        if ch in forbidden:
            continue
        out_chars.append(ch)
    name = ''.join(out_chars).strip(' .')
    if not name or name in ('.', '..'):
        return None

    root, ext = os.path.splitext(name)
    if not root:
        return None
    # Windows：保留名加后缀，避免无法创建文件
    if root.upper() in _WIN_RESERVED_NAMES:
        root = root + '_'
        name = root + ext
    if len(name) > max_len:
        ext = ext[:20] if len(ext) > 20 else ext
        root = root[: max(1, max_len - len(ext))]
        name = root + ext
    if '/' in name or '\\' in name or '..' in name:
        return None
    return name


def _safe_ext_from_original_for_fallback(original: str) -> str:
    """仅用于无法得到合法 basename 时的回退名：从原始串取 ASCII 扩展名。"""
    if not original:
        return ''
    base = original.replace('\\', '/').rstrip('/').split('/')[-1]
    ext = os.path.splitext(base)[1]
    return ext if re.match(r'^\.[A-Za-z0-9]{1,15}$', ext) else ''


# 初始化 Flask 应用
TIE_PREFIX = '/TIE'
app = Flask(__name__, static_url_path=f'{TIE_PREFIX}/static')
app.config['SECRET_KEY'] = 'your-secret-key-here-change-in-production'

# 确保 instance 文件夹存在
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(basedir, "instance", "app.db")}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 文件上传配置
UPLOAD_FOLDER = os.path.join(basedir, 'uploads')
MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500MB 限制
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'bmp', 'gif', 'tiff', 'webp'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# 确保上传目录存在
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# 确保 instance 目录存在（数据库文件存放目录）
os.makedirs(os.path.join(basedir, 'instance'), exist_ok=True)

# 初始化 Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'tie.login'
login_manager.login_message = '请先登录'

# 导入模型并从 models 中获取 db 实例
from models import db, User

# 初始化数据库
db.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    """加载用户"""
    return User.query.get(int(user_id))

# ==================== 路由 ====================

tie = Blueprint('tie', __name__)

@tie.route('/')
@tie.route('/index')
def index():
    """首页"""
    return render_template('index.html')

@tie.route('/dashboard')
@login_required
def dashboard():
    """用户仪表盘"""
    return render_template('dashboard.html')

@tie.route('/intelligent-analysis')
@login_required
def intelligent_analysis():
    """智能解析页面"""
    return render_template('intelligent_analysis.html')

@tie.route('/data-review')
@login_required
def data_review():
    """数据复核：轻量矩形标注（Fabric，与 /review-editor 相同页面）"""
    return render_template('review_editor.html')

@tie.route('/review-editor')
@login_required
def review_editor():
    """数据复核编辑器（别名，便于书签与旧链接）"""
    return render_template('review_editor.html')

# ========== 数据复核 API ==========
@tie.route('/api/review/files')
@login_required
def get_review_files():
    """获取用户的所有可复核文件列表"""
    user_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(current_user.id))
    
    if not os.path.exists(user_folder):
        return jsonify({'files': []})
    
    files = []
    # 扫描所有 jpg 和 png 文件
    for img_pattern in ['*.jpg', '*.png']:
        for img_path in glob.glob(os.path.join(user_folder, img_pattern)):
            filename = os.path.basename(img_path)
            # 预览图不作为“可复核文件”展示（由 /api/review/image?preview=1 自动使用）
            if '.preview.' in filename:
                continue
            base_name = os.path.splitext(filename)[0]
            source_json = f"{base_name}.json"
            review_json = f"{base_name}.review.json"
            source_path = os.path.join(user_folder, source_json)
            review_path = os.path.join(user_folder, review_json)
            files.append({
                'name': base_name,
                'image': filename,
                'json': source_json,
                'review_json': review_json,
                'has_json': os.path.isfile(source_path),
                'has_review_json': os.path.isfile(review_path),
            })
    
    # 按文件名排序
    files.sort(key=lambda x: x['name'])
    
    return jsonify({'files': files})

@tie.route('/api/review/image/<path:filename>')
@login_required
def get_review_image(filename):
    """返回图片文件"""
    # 分离文件名和查询参数
    if '?' in filename:
        base_filename = filename.split('?')[0]
    else:
        base_filename = filename
    
    user_folder_review = os.path.join(app.config['UPLOAD_FOLDER'], str(current_user.id))

    # 若请求预览图，优先返回同名 *.preview.<ext>
    want_preview = str(request.args.get('preview', '')).strip() in ('1', 'true', 'True', 'yes')
    candidate_name = base_filename
    if want_preview:
        stem, ext0 = os.path.splitext(base_filename)
        if ext0:
            preview_name = f"{stem}.preview{ext0}"
            preview_path = _review_file_in_user_dir(user_folder_review, preview_name)
            if preview_path and os.path.isfile(preview_path):
                candidate_name = preview_name

    image_path = _review_file_in_user_dir(user_folder_review, candidate_name)
    
    if not image_path or not os.path.isfile(image_path):
        return jsonify({'error': '图片不存在'}), 404
    
    # 确定 MIME 类型
    ext = os.path.splitext(image_path)[1].lower()
    mime_types = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp'
    }
    mimetype = mime_types.get(ext, 'image/jpeg')
    
    resp = send_file(image_path, mimetype=mimetype)
    resp.headers['Cache-Control'] = 'no-store, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    return resp


def _review_image_basename_ok(name):
    if not name or '..' in name or '/' in name or '\\' in name:
        return False
    return os.path.basename(name) == name


def _review_stem_from_json_filename(filename):
    """
    由标注 JSON 文件名得到与图片相同的主名（不含扩展名）。
    foo.review.json -> foo（不是 foo.review，否则找不到同名图片）
    bar.json -> bar
    """
    if not filename:
        return ''
    fn = filename.strip()
    low = fn.lower()
    if low.endswith('.review.json'):
        return fn[:-len('.review.json')]
    if low.endswith('.json'):
        return fn[:-5]
    return os.path.splitext(fn)[0]


def _no_cache_json_response(payload, status=200):
    """标注 JSON 随文件常变，禁止缓存，避免页面/浏览器仍显示旧版本。"""
    resp = jsonify(payload)
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    resp.status_code = status
    return resp


@tie.route('/api/review/json/<filename>')
@login_required
def get_review_json(filename):
    """返回 JSON 标注文件"""
    user_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(current_user.id))
    if not _json_basename_ok(filename):
        return _no_cache_json_response({'error': '文件名格式非法'}, 400)
    json_path = _review_file_in_user_dir(user_folder, filename)
    
    if json_path and os.path.isfile(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return _no_cache_json_response(data)
        except Exception as e:
            return _no_cache_json_response({'error': f'JSON 解析失败：{str(e)}'}, 500)
    return _no_cache_json_response({'error': 'JSON 文件不存在'}, 404)


@tie.route('/api/review/annotations-for/<path:image_filename>')
@login_required
def get_review_annotations_for_image(image_filename):
    """
    对与图片同主名的 *.review.json 与 *.json，取修改时间较新的一份返回。
    避免仅优先读 review 时，磁盘上已更新的解析 json 却被忽略。
    """
    if '?' in image_filename:
        image_filename = image_filename.split('?')[0]
    if not _review_image_basename_ok(image_filename):
        return _no_cache_json_response({'error': '非法图片名'}, 400)

    user_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(current_user.id))
    stem = os.path.splitext(image_filename)[0]
    review_name = f'{stem}.review.json'
    source_name = f'{stem}.json'
    review_path = _review_file_in_user_dir(user_folder, review_name)
    source_path = _review_file_in_user_dir(user_folder, source_name)

    candidates = []
    if review_path and os.path.isfile(review_path):
        candidates.append((review_path, os.path.getmtime(review_path)))
    if source_path and os.path.isfile(source_path):
        candidates.append((source_path, os.path.getmtime(source_path)))
    if not candidates:
        return _no_cache_json_response({'error': '无标注 JSON'}, 404)

    best_path = max(candidates, key=lambda x: x[1])[0]
    try:
        with open(best_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            payload = {k: v for k, v in data.items()}
        else:
            payload = {'info': data}

        # 若 JSON 内未记录原图尺寸，则从同名图片读取一次（用于预览图坐标缩放）
        try:
            if not payload.get('image_size'):
                img_path = _review_file_in_user_dir(user_folder, image_filename)
                if img_path and os.path.isfile(img_path):
                    with Image.open(img_path) as im:
                        payload['image_size'] = [int(im.size[0]), int(im.size[1])]
        except Exception:
            pass

        # 若存在预览图，也带上预览尺寸（便于前端/诊断；不强依赖）
        try:
            if not payload.get('preview_size'):
                stem, ext0 = os.path.splitext(image_filename)
                prev_name = f"{stem}.preview{ext0}"
                prev_path = _review_file_in_user_dir(user_folder, prev_name)
                if prev_path and os.path.isfile(prev_path):
                    with Image.open(prev_path) as im:
                        payload['preview_size'] = [int(im.size[0]), int(im.size[1])]
        except Exception:
            pass

        payload['_review_source'] = {
            'file': os.path.basename(best_path),
            'userId': current_user.id,
            'mtime': int(os.path.getmtime(best_path)),
        }
        return _no_cache_json_response(payload)
    except Exception as e:
        return _no_cache_json_response({'error': f'JSON 解析失败：{str(e)}'}, 500)


@tie.route('/api/review/save', methods=['POST'])
@login_required
def save_review_data():
    """保存复核标注：默认写入 *.review.json（含 version/format/样式等）；annotations 可为列表或含 info 的字典。"""
    data = request.json or {}
    filename = data.get('filename')
    annotations = data.get('annotations')
    
    if not filename or annotations is None:
        return jsonify({'error': '参数错误：需要 filename 与 annotations'}), 400
    if not isinstance(annotations, (list, dict)):
        return jsonify({'error': 'annotations 须为数组或含 info 的对象'}), 400
    
    if isinstance(annotations, list):
        data_to_write = {'info': annotations}
    else:
        info = annotations.get('info')
        if not isinstance(info, list):
            return jsonify({'error': '对象格式须包含 info 数组'}), 400
        data_to_write = {k: v for k, v in annotations.items() if k != 'info'}
        data_to_write['info'] = info
    
    if not _json_basename_ok(filename):
        return jsonify({'error': '文件名格式非法'}), 400
    
    user_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(current_user.id))
    json_path = _review_file_in_user_dir(user_folder, filename)
    if not json_path:
        return jsonify({'error': '非法路径访问'}), 403
    
    if not os.path.isfile(json_path):
        stem_new = _review_stem_from_json_filename(filename)
        has_sibling_image = False
        for ext in ('.jpg', '.jpeg', '.png', '.JPG', '.JPEG', '.PNG', '.webp', '.WEBP'):
            img_candidate = _review_file_in_user_dir(user_folder, stem_new + ext)
            if img_candidate and os.path.isfile(img_candidate):
                has_sibling_image = True
                break
        if not has_sibling_image:
            return jsonify({'error': '尚无 JSON 且无同名图片，无法新建标注文件'}), 404
    
    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data_to_write, f, ensure_ascii=False, indent=4)

        # 复核保存为 *.review.json 时，同步一份 info 到同名 *.json，便于 IDE/解析文件与界面一致
        if filename.lower().endswith('.review.json'):
            stem = _review_stem_from_json_filename(filename)
            source_path = _review_file_in_user_dir(user_folder, f'{stem}.json')
            if source_path:
                info_only = data_to_write.get('info')
                if isinstance(info_only, list):
                    clean_info = []
                    for item in info_only:
                        if isinstance(item, dict):
                            clean_info.append({
                                k: v for k, v in item.items()
                                if not (isinstance(k, str) and k.startswith('_'))
                            })
                        else:
                            clean_info.append(item)
                    with open(source_path, 'w', encoding='utf-8') as sf:
                        json.dump({'info': clean_info}, sf, ensure_ascii=False, indent=4)
        
        return jsonify({
            'success': True,
            'message': '保存成功'
        })
    except Exception as e:
        return jsonify({'error': f'保存失败：{str(e)}'}), 500


@tie.route('/api/review/export-jpg', methods=['POST'])
@login_required
def export_review_jpg():
    """
    接收前端渲染后的 JPG（与浏览器显示一致），保存到用户目录的 EXPORT/ 下，重名直接覆盖。
    表单字段：
      - image: 原始图片文件名（用于生成导出文件名）
      - file: 上传的 jpg 二进制
    """
    user_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(current_user.id))
    image_name = (request.form.get('image') or '').strip()
    if not _review_image_basename_ok(image_name):
        return jsonify({'error': '非法图片名'}), 400

    f = request.files.get('file')
    if not f:
        return jsonify({'error': '缺少上传文件 file'}), 400

    export_dir = os.path.join(user_folder, 'EXPORT')
    os.makedirs(export_dir, exist_ok=True)
    stem = os.path.splitext(image_name)[0]
    out_path = os.path.join(export_dir, f'{stem}.jpg')

    try:
        data = f.read()
        if not data:
            return jsonify({'error': '空文件'}), 400
        # 简单校验 JPEG 头 FF D8
        if not (len(data) >= 2 and data[0] == 0xFF and data[1] == 0xD8):
            return jsonify({'error': '不是有效的 JPG'}), 400
        with open(out_path, 'wb') as wf:
            wf.write(data)
        return jsonify({'success': True, 'file': os.path.basename(out_path)})
    except Exception as e:
        return jsonify({'error': f'导出失败：{str(e)}'}), 500


@tie.route('/api/review/export-zip', methods=['POST'])
@login_required
def download_export_zip():
    """
    将用户 EXPORT/ 下的导出 JPG 按请求列表打包为 zip 下载。
    JSON body: { images: ["xxx.jpg", ...] } 这里的 images 是原始图片文件名（用于定位 EXPORT/<stem>.jpg）
    """
    data = request.json or {}
    images = data.get('images') or []
    if not isinstance(images, list) or not images:
        return jsonify({'error': '参数错误：需要 images 数组'}), 400

    user_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(current_user.id))
    export_dir = os.path.join(user_folder, 'EXPORT')
    if not os.path.isdir(export_dir):
        return jsonify({'error': 'EXPORT 目录不存在'}), 404

    buf = io.BytesIO()
    added = 0
    with zipfile.ZipFile(buf, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
        for img_name in images:
            if not isinstance(img_name, str):
                continue
            img_name = img_name.strip()
            if not _review_image_basename_ok(img_name):
                continue
            stem = os.path.splitext(img_name)[0]
            p = os.path.join(export_dir, f'{stem}.jpg')
            if os.path.isfile(p):
                zf.write(p, arcname=os.path.basename(p))
                added += 1

    if added == 0:
        return jsonify({'error': '没有找到可打包的导出文件'}), 404

    buf.seek(0)
    filename = f'EXPORT_{datetime.now().strftime("%Y%m%d%H%M%S")}.zip'
    resp = send_file(buf, mimetype='application/zip', as_attachment=True, download_name=filename)
    resp.headers['Cache-Control'] = 'no-store, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    return resp

@tie.route('/profile')
@login_required
def profile():
    """用户资料"""
    return render_template('profile.html')

@tie.route('/login', methods=['GET', 'POST'])
def login():
    """登录"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            user.update_last_login()
            next_page = request.args.get('next')
            flash('登录成功！', 'success')
            return redirect(next_page or url_for('tie.dashboard'))
        else:
            flash('用户名或密码错误', 'error')
    
    return render_template('login.html')

@tie.route('/logout')
@login_required
def logout():
    """登出"""
    logout_user()
    flash('已退出登录', 'info')
    return redirect(url_for('tie.index'))

@tie.route('/register', methods=['GET', 'POST'])
def register():
    """注册 - 只有超级管理员可以访问"""
    # 检查是否为超级管理员
    if not current_user.is_authenticated or not current_user.is_super_admin():
        flash('只有超级管理员才能注册新账号', 'error')
        return redirect(url_for('tie.index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')  # 可选
        password = request.form.get('password', '123456!')  # 默认密码
        level = request.form.get('level', 1, type=int)  # 用户等级
        
        # 验证（只验证用户名必填）
        if not username:
            flash('用户名是必填的', 'error')
            return redirect(request.url)
        
        # 如果填写了邮箱，检查是否已被注册
        if email and User.query.filter_by(email=email).first():
            flash('邮箱已被注册', 'error')
            return redirect(request.url)
        
        if User.query.filter_by(username=username).first():
            flash('用户名已被使用', 'error')
            return redirect(request.url)
        
        # 创建用户（邮箱可选）
        user = User(username=username, email=email, level=level)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        flash(f'用户 {username} 创建成功！默认密码：{password}', 'success')
        return redirect(url_for('tie.manage_users'))
    
    return render_template('admin_register.html')

@tie.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    """修改密码"""
    if request.method == 'POST':
        old_password = request.form.get('old_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        # 验证新密码
        if not new_password or len(new_password) < 6:
            flash('密码长度至少为 6 位', 'error')
            return redirect(request.url)
        
        if new_password != confirm_password:
            flash('两次输入的新密码不一致', 'error')
            return redirect(request.url)
        
        # 检查是否为超级管理员
        if current_user.is_super_admin():
            # 超级管理员可以直接修改任何用户密码
            target_username = request.form.get('target_username')
            if target_username:
                target_user = User.query.filter_by(username=target_username).first()
                if target_user:
                    target_user.set_password(new_password)
                    db.session.commit()
                    flash(f'用户 {target_username} 的密码已修改', 'success')
                    return redirect(url_for('tie.manage_users'))
        else:
            # 普通用户需要验证原密码
            if not old_password or not current_user.check_password(old_password):
                flash('原密码错误', 'error')
                return redirect(request.url)
            
            # 修改当前用户密码
            current_user.set_password(new_password)
            db.session.commit()
            flash('密码修改成功', 'success')
            return redirect(url_for('tie.profile'))
    
    return render_template('change_password.html')

@tie.route('/admin/users')
@login_required
def manage_users():
    """用户管理 - 只有超级管理员可以访问"""
    if not current_user.is_super_admin():
        flash('无权访问此页面', 'error')
        return redirect(url_for('tie.index'))
    
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('manage_users.html', users=users)

@tie.route('/admin/configure_user_api/<int:user_id>', methods=['GET', 'POST'])
@login_required
def configure_user_api(user_id):
    """管理员配置用户 API - 只有超级管理员可以访问"""
    if not current_user.is_super_admin():
        flash('无权访问此页面', 'error')
        return redirect(url_for('tie.index'))
    
    user = User.query.get_or_404(user_id)
    
    if request.method == 'POST':
        api_key = request.form.get('api_key')
        base_url = request.form.get('base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
        model_name = request.form.get('model_name', 'qwen-vl-max')
        
        # 更新用户 API 配置
        user.api_key = api_key
        user.base_url = base_url
        user.model_name = model_name
        db.session.commit()
        
        flash(f'用户 {user.username} 的 API 配置已更新', 'success')
        return redirect(url_for('tie.manage_users'))
    
    return render_template('configure_user_api.html', user=user)

@tie.route('/configure_api', methods=['GET', 'POST'])
@login_required
def configure_api():
    """用户自己配置 API"""
    if request.method == 'POST':
        api_key = request.form.get('api_key', '').strip()
        base_url = request.form.get('base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1').strip()
        model_name = request.form.get('model_name', 'qwen-vl-max')
        
        if not api_key:
            flash('API Key 不能为空', 'error')
            return redirect(url_for('tie.configure_api'))
        
        # 更新当前用户的 API 配置
        current_user.api_key = api_key
        current_user.base_url = base_url
        current_user.model_name = model_name
        db.session.commit()
        
        flash('✅ API 配置已保存', 'success')
        return redirect(url_for('tie.profile'))
    
    return render_template('configure_api.html')

@tie.route('/upload', methods=['POST'])
@login_required
def upload_file():
    """处理文件上传"""
    image_list = []
    filepath = None
    json_save_path = None
    try:
        if 'file' not in request.files:
            return jsonify({'error': '没有文件上传'}), 400
        # 获取用户信息
        username = current_user.username
        user_id = current_user.id
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'error': '文件名为空'}), 400
        
        # 获取文档类型和目标姓名
        doc_type = request.form.get('doc_type', '')
        target_name = request.form.get('target_name', '')
        
        # 保存文件：保留中文文件名；仅剔除路径穿越与非法字符（不用 secure_filename，避免整段清空中文）
        filename = _safe_upload_basename_unicode(file.filename)
        if not filename:
            ext = _safe_ext_from_original_for_fallback(file.filename)
            filename = f"upload_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
        save_filename = filename
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], str(user_id), save_filename)
        dir_name = os.path.dirname(filepath)
        os.makedirs(dir_name, exist_ok=True)  # 创建目录（如果不存在）
        # 保存上传的文件
        file.save(filepath)
        
        # 获取文件大小
        file_size = os.path.getsize(filepath)
        

        
        # 获取用户 API 配置
        api_key = current_user.api_key or ''
        base_url = current_user.base_url or 'https://dashscope.aliyuncs.com/compatible-mode/v1'
        model_name = current_user.model_name or 'qwen-vl-max'
        
        # 检查 API 密钥是否配置
        if not api_key or api_key.strip() == '':
            if filepath and os.path.exists(filepath):
                os.remove(filepath)
            return jsonify({
                'error': '❌ API 密钥未配置，请先在用户设置中配置 API 密钥',
                'need_config': True
            }), 400
        
        print(f"\n{'='*60}")
        print(f"【用户信息】")
        print(f"  用户名：{username}")
        print(f"  用户 ID: {user_id}")
        print(f"\n【API 配置】")
        print(f"  API Key: {api_key[:20]}..." if api_key else "  API Key: 未配置")
        print(f"  Base URL: {base_url}")
        print(f"  Model Name: {model_name}")
        print(f"\n【文件信息】")
        print(f"  文件名：{filename}")
        print(f"  保存路径：{filepath}")
        print(f"  文件大小：{format_file_size(file_size)}")
        print(f"  文档类型：{doc_type}")
        print(f"  目标姓名：{target_name}")
        print(f"{'='*60}\n")
        
        image_list = merge_llm_post(
            file_path=filepath, 
            check_class=doc_type,
            name=target_name, 
            model_name=model_name, 
            api_key=api_key, 
            base_url=base_url, 
            progress_callback=None
            )
        # 写入为json

        json_save_path = f"{os.path.splitext(filepath)[0]}.json"
        os.remove(filepath)
        return jsonify({
            'success': True,
            'filename': filename,
            'save_filename': save_filename,
            'filepath': filepath,
            'size': file_size,
            'username': username,
            'api_key': api_key,
            'base_url': base_url,
            'model_name': model_name,
            'doc_type': doc_type,
            'target_name': target_name,
            'message': '文件上传成功'
        })
        
    except Exception as e:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
        if json_save_path and os.path.exists(json_save_path):
            os.remove(json_save_path)
        for image_path in image_list:
            if os.path.exists(image_path):
                os.remove(image_path)
        print(f"上传失败：{str(e)}")
        return jsonify({'error': str(e)}), 500

def format_file_size(size):
    """格式化文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} TB"


def _dir_size_bytes(root_dir: str) -> int:
    total = 0
    if not root_dir or not os.path.isdir(root_dir):
        return 0
    for base, dirs, files in os.walk(root_dir):
        for name in files:
            fp = os.path.join(base, name)
            try:
                if os.path.islink(fp):
                    continue
                total += os.path.getsize(fp)
            except OSError:
                continue
    return total


@tie.route('/api/storage/usage')
@login_required
def tie_storage_usage():
    """
    统计当前登录用户在 uploads/<id>/ 下占用空间（字节）。
    用于智能解析页提示：超过 1GB 需提醒清理。
    """
    user_dir = os.path.join(app.config['UPLOAD_FOLDER'], str(current_user.id))
    used = _dir_size_bytes(user_dir)
    limit = 1024 * 1024 * 1024  # 1GB
    return jsonify({
        'user_id': current_user.id,
        'used_bytes': used,
        'limit_bytes': limit,
        'over_limit': used > limit
    })


@tie.route('/api/storage/clear', methods=['POST'])
@login_required
def tie_storage_clear():
    """
    清理当前登录用户 uploads/<id>/ 下的残存文件（含解析产物、图片、EXPORT 等）。
    注意：这是“项目清理按钮”的后端实现，前端必须二次确认。
    """
    user_dir = os.path.join(app.config['UPLOAD_FOLDER'], str(current_user.id))
    if not os.path.isdir(user_dir):
        return jsonify({'success': True, 'deleted_files': 0, 'freed_bytes': 0})

    deleted = 0
    freed = 0
    # 只删除 user_dir 内文件，保留目录结构
    for base, dirs, files in os.walk(user_dir):
        for name in files:
            fp = os.path.join(base, name)
            try:
                if os.path.islink(fp):
                    continue
                sz = os.path.getsize(fp)
                os.remove(fp)
                deleted += 1
                freed += sz
            except OSError:
                continue
    return jsonify({'success': True, 'deleted_files': deleted, 'freed_bytes': freed})

# 将整个业务挂载到 /TIE 前缀下（避免与服务器其他业务路由冲突）
app.register_blueprint(tie, url_prefix=TIE_PREFIX)


@app.route('/')
def root_redirect():
    """站点根路径重定向到业务首页（蓝图在 /TIE 下，直接访问 / 会 404）。"""
    return redirect(url_for('tie.index'))


# 错误处理
@app.errorhandler(404)
def not_found_error(error):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('errors/500.html'), 500

# 上下文处理器
@app.context_processor
def inject_globals():
    """注入全局变量到所有模板"""
    return {
        'current_year': datetime.now().year,
        'user_level_names': {
            1: '普通会员',
            2: '高级会员',
            3: 'VIP 会员',
            4: '超级 VIP',
            5: '管理员'
        }
    }

if __name__ == '__main__':
    # 创建数据库表
    with app.app_context():
        db.create_all()
        
        # 创建超级管理员账号
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(username='admin', email='admin@example.com', is_admin=True, level=5)
            admin.set_password('admin123!')  # 默认密码
            db.session.add(admin)
            db.session.commit()
            print("✅ 超级管理员账号已创建：admin / admin123!")
        else:
            print("ℹ️  超级管理员账号已存在")
    
    # 运行应用
    app.run(debug=True, host='0.0.0.0', port=5000)
