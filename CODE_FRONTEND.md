# 前端与其他关键细节

## 🖥️ 前端架构

### 页面结构

```
templates/
├── base.html                    # 基础模板（导航栏、样式等）
├── index.html                   # 首页
├── login.html                   # 登录页
├── register.html                # 用户注册页（公开）
├── admin_register.html          # 管理员注册用户页（仅超管）
├── dashboard.html               # 用户仪表板
├── profile.html                 # 用户资料页
├── change_password.html         # 修改密码页
├── intelligent_analysis.html    # 智能解析页（上传文件）
├── review_editor.html           # 数据复核编辑器（Fabric.js）
├── manage_users.html            # 用户管理页（仅超管）
├── configure_user_api.html      # 配置用户 API（仅超管）
└── errors/
    ├── 404.html                 # 404 错误页
    └── 500.html                 # 500 错误页

static/
├── main.js                      # 主要 JavaScript 逻辑
└── style.css                    # 样式表
```

### 核心 JavaScript 功能

**main.js** 应包含以下核心功能：

#### 1️⃣ 智能解析页 (intelligent_analysis.html)

```javascript
// 1. 文件上传表单
function handleUpload() {
    const fileInput = document.getElementById('file');
    const docType = document.getElementById('doc_type').value;
    const targetName = document.getElementById('target_name').value;
    
    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    formData.append('doc_type', docType);
    formData.append('target_name', targetName);
    
    fetch('/TIE/upload', {
        method: 'POST',
        body: formData
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            alert('上传成功！');
            // 刷新可复核文件列表
            loadReviewFiles();
        } else {
            alert('错误：' + data.error);
        }
    });
}

// 2. 获取存储使用情况
function checkStorageUsage() {
    fetch('/TIE/api/storage/usage')
    .then(res => res.json())
    .then(data => {
        const used = (data.used_bytes / 1024 / 1024 / 1024).toFixed(2);
        const limit = (data.limit_bytes / 1024 / 1024 / 1024).toFixed(2);
        
        document.getElementById('storage-info').innerText = 
            `已用: ${used} GB / 限制: ${limit} GB`;
        
        if (data.over_limit) {
            document.getElementById('clear-btn').classList.remove('hidden');
        }
    });
}

// 3. 清理存储
function clearStorage() {
    if (confirm('确认删除所有文件？此操作不可撤销！')) {
        fetch('/TIE/api/storage/clear', {
            method: 'POST'
        })
        .then(res => res.json())
        .then(data => {
            alert(`已删除 ${data.deleted_files} 个文件，释放 ${(data.freed_bytes / 1024 / 1024).toFixed(2)} MB`);
            checkStorageUsage();
        });
    }
}
```

#### 2️⃣ 数据复核编辑器 (review_editor.html)

```javascript
// 使用 Fabric.js 进行交互式标注编辑
const canvas = new fabric.Canvas('annotation-canvas');

// 1. 加载可复核文件列表
function loadReviewFiles() {
    fetch('/TIE/api/review/files')
    .then(res => res.json())
    .then(data => {
        const fileList = document.getElementById('file-list');
        fileList.innerHTML = '';
        
        data.files.forEach(file => {
            const item = document.createElement('div');
            item.className = 'file-item';
            item.innerText = file.name;
            item.onclick = () => loadFile(file);
            fileList.appendChild(item);
        });
    });
}

// 2. 加载选中的文件及其标注
function loadFile(file) {
    // 获取图片
    fetch(`/TIE/api/review/image/${file.image}?preview=1`)
    .then(res => res.blob())
    .then(blob => {
        const url = URL.createObjectURL(blob);
        
        // 获取标注数据
        return fetch(`/TIE/api/review/annotations-for/${file.image}`)
            .then(res => res.json())
            .then(annotations => ({url, annotations}));
    })
    .then(({url, annotations}) => {
        // 加载图片到 Canvas
        fabric.Image.fromURL(url, (img) => {
            canvas.setDimensions({
                width: img.width,
                height: img.height
            });
            canvas.setBackgroundImage(img, canvas.renderAll.bind(canvas));
            
            // 加载标注框
            loadAnnotations(annotations, file);
        });
    });
}

// 3. 将 JSON 标注转为 Fabric 对象
function loadAnnotations(annotationData, file) {
    const info = annotationData.info || [];
    const imageSize = annotationData.image_size || [canvas.width, canvas.height];
    const previewSize = annotationData.preview_size || imageSize;
    
    // 计算坐标缩放比例（从原图到预览图）
    const scale = {
        x: previewSize[0] / imageSize[0],
        y: previewSize[1] / imageSize[1]
    };
    
    info.forEach(item => {
        const [x1, y1, x2, y2] = item.box;
        
        // 缩放坐标到预览图
        const scaledBox = [
            x1 * scale.x, y1 * scale.y,
            x2 * scale.x, y2 * scale.y
        ];
        
        // 创建矩形框
        const rect = new fabric.Rect({
            left: scaledBox[0],
            top: scaledBox[1],
            width: scaledBox[2] - scaledBox[0],
            height: scaledBox[3] - scaledBox[1],
            fill: 'transparent',
            stroke: item['标红'] ? 'red' : 'blue',
            strokeWidth: 2,
            selectable: true,
            // 自定义数据
            _data: item
        });
        
        canvas.add(rect);
    });
    
    canvas.renderAll();
    currentFile = file;  // 保存当前文件信息
}

// 4. 编辑标注（用户可以拖拽、删除、修改）
function updateAnnotation(rect, changes) {
    // rect._data 包含原始 JSON 数据
    Object.assign(rect._data, changes);
    canvas.renderAll();
}

// 5. 保存复核结果
function saveAnnotations() {
    // 从 Canvas 提取所有框
    const info = canvas.getObjects('rect').map(rect => ({
        title: rect._data.title,
        box: [
            Math.round(rect.left),
            Math.round(rect.top),
            Math.round(rect.left + rect.width),
            Math.round(rect.top + rect.height)
        ],
        内容: rect._data['内容'],
        标红: rect._data['标红'],
        页码: rect._data['页码']
    }));
    
    const filename = currentFile.image.replace(/\.jpg$/, '') + '.review.json';
    
    fetch('/TIE/api/review/save', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            filename: filename,
            annotations: {info}
        })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            alert('保存成功！');
        } else {
            alert('错误：' + data.error);
        }
    });
}

// 6. 导出标注图片
function exportImage() {
    canvas.toBlob((blob) => {
        const formData = new FormData();
        formData.append('image', currentFile.image);
        formData.append('file', blob, 'annotation.jpg');
        
        fetch('/TIE/api/review/export-jpg', {
            method: 'POST',
            body: formData
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                alert('导出成功：' + data.file);
            } else {
                alert('错误：' + data.error);
            }
        });
    }, 'image/jpeg');
}

// 7. 批量下载导出
function downloadExportZip(imageNames) {
    fetch('/TIE/api/review/export-zip', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({images: imageNames})
    })
    .then(res => res.blob())
    .then(blob => {
        // 下载 ZIP
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'export.zip';
        a.click();
    });
}
```

### Fabric.js 交互特性

```javascript
// 初始化 Canvas
const canvas = new fabric.Canvas('annotation-canvas', {
    selection: true,              // 允许多选
    preserveObjectStacking: true  // 保持图层顺序
});

// 事件监听：对象移动时
canvas.on('object:modified', (e) => {
    const obj = e.target;
    // 更新对象的 _data（后续保存时用）
    console.log('对象已修改:', obj._data);
});

// 事件监听：删除对象
canvas.on('object:removed', (e) => {
    console.log('对象已删除');
});

// 右键菜单或快捷键删除
document.addEventListener('keydown', (e) => {
    if (e.key === 'Delete') {
        const activeObjects = canvas.getActiveObjects();
        activeObjects.forEach(obj => canvas.remove(obj));
        canvas.discardActiveObject();
        canvas.renderAll();
    }
});
```

---

## 🗂️ 项目配置文件

### requirements.txt 重要包说明

```
Flask==3.1.3                    # Web 框架
Flask-Login==0.6.3              # 用户认证
Flask-SQLAlchemy==3.1.1         # ORM
SQLAlchemy==...                 # 数据库引擎

opencv-python==4.13.0.92        # 图像处理
Pillow==12.2.0                  # PIL 库
PyMuPDF==1.27.2.2              # PDF 处理（fitz）

openai==2.30.0                 # LLM 调用（兼容 OpenAI API）
requests==...                  # HTTP 库

numpy==2.4.4                   # 数值计算
pandas==3.0.2                  # 数据处理

Jinja2==3.1.6                  # 模板引擎
```

### 数据库初始化

```python
# app.py 启动时自动执行
if __name__ == '__main__':
    with app.app_context():
        # 创建所有表
        db.create_all()
        
        # 如果超级管理员不存在，创建默认账号
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(
                username='admin',
                email='admin@example.com',
                is_admin=True,
                level=5
            )
            admin.set_password('admin123!')
            db.session.add(admin)
            db.session.commit()
            print("✅ 超级管理员账号已创建: admin / admin123!")
```

**数据库表**：
```
users
  ├─ id: INTEGER PRIMARY KEY
  ├─ username: VARCHAR(64) UNIQUE
  ├─ email: VARCHAR(120) UNIQUE
  ├─ password_hash: VARCHAR(256)
  ├─ created_at: DATETIME
  ├─ last_login: DATETIME
  ├─ is_active: BOOLEAN
  ├─ is_admin: BOOLEAN
  ├─ level: INTEGER (1-5)
  ├─ experience: INTEGER
  ├─ credits: INTEGER
  ├─ api_key: VARCHAR(256)
  ├─ base_url: VARCHAR(500)
  └─ model_name: VARCHAR(100)
```

---

## 🔄 核心交互流程图

### 用户上传与解析

```
用户选择文件 → 选择文档类型 → 输入目标姓名（可选）
     ↓
POST /upload (multipart/form-data)
     ↓
后端验证（文件类型、大小、用户身份）
     ↓
保存到 uploads/<user_id>/<filename>
     ↓
merge_llm_post() [详见 utils.py]
  ├─ 文件类型判断（PDF/图片）
  ├─ 图片缩放到 1000×1000
  ├─ 转 Base64 编码
  ├─ 读取 prompt/system.txt + prompt/<doc_type>.txt
  ├─ 调用 OpenAI 兼容 API
  ├─ 解析 LLM 返回的 JSON
  ├─ 二次调用 LLM 进行翻译统一
  ├─ 坐标变换（1000×1000 → 原图）
  ├─ 绘制标注框和文本
  ├─ 保存原图注解：<stem>_1.jpg
  ├─ 生成预览图：<stem>_1.preview.jpg
  └─ 保存 JSON：<stem>_1.json
     ↓
删除原上传文件
     ↓
返回 200 OK
     ↓
前端刷新可复核文件列表
```

### 数据复核

```
点击文件进入复核编辑器
     ↓
获取文件列表：GET /api/review/files
     ↓
加载图片：GET /api/review/image/<file>?preview=1
     ↓
加载标注：GET /api/review/annotations-for/<file>
     ↓
Fabric.js 呈现图片和可拖拽的框
     ↓
用户编辑（拖拽、删除、修改）
     ↓
用户点击「保存」
     ↓
POST /api/review/save
     ↓
保存为 <stem>.review.json
同步更新 <stem>.json
     ↓
返回 200 OK
     ↓
显示成功提示
```

### 导出工作流

```
复核完毕 → 点击「导出此页」
     ↓
前端：canvas.toBlob() 生成 JPG
     ↓
上传 JPG：POST /api/review/export-jpg
     ↓
保存到 uploads/<user_id>/EXPORT/<stem>.jpg
     ↓
点击「批量下载」
     ↓
选择要下载的文件列表
     ↓
POST /api/review/export-zip (images: [...])
     ↓
服务器打包 ZIP
     ↓
浏览器下载 EXPORT_<timestamp>.zip
```

---

## 🔐 安全性细节

### 1️⃣ CSRF 防护
```html
<!-- 所有 POST 表单都应包含 CSRF token -->
<form method="POST">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    ...
</form>
```

### 2️⃣ SQL 注入防护
```python
# 使用 ORM 的参数化查询，不拼接 SQL
user = User.query.filter_by(username=username).first()  # ✅ 安全

# 不要这样做：
# user = User.query.filter(f"username = '{username}'").first()  # ❌ 危险
```

### 3️⃣ 路径穿越防护
```python
# 每个文件访问都需要检查
def _review_file_in_user_dir(user_folder, filename):
    full_r = os.path.realpath(file_path)
    user_r = os.path.realpath(user_folder)
    
    # 确保实际路径在用户目录内
    if os.path.commonpath([full_r, user_r]) != user_r:
        return None  # 非法访问！
```

### 4️⃣ 文件上传验证
```python
# 检查文件扩展名
if not filename.lower().endswith(tuple(ALLOWED_EXTENSIONS)):
    return jsonify({'error': '不支持的文件类型'}), 400

# 检查文件大小
if file_size > MAX_CONTENT_LENGTH:
    return jsonify({'error': '文件过大'}), 413
```

### 5️⃣ 密码存储
```python
# 使用 werkzeug.security 进行密码哈希
def set_password(self, password):
    self.password_hash = generate_password_hash(password)

def check_password(self, password):
    return check_password_hash(self.password_hash, password)
```

---

## ⚡ 性能优化

### 1️⃣ 预览图缩放

**问题**：原始 OCR 图片可能 2000×3000px，用 Fabric.js 直接渲染会卡顿。

**解决**：
```python
# 生成预览图（长边 ≤ 1600px）
h0, w0 = img_bgr.shape[:2]
max_edge = 1600
scale = min(1.0, float(max_edge) / float(max(w0, h0)))

if scale < 0.999:
    preview = cv2.resize(img_bgr, (pw, ph), interpolation=cv2.INTER_AREA)
else:
    preview = img_bgr

cv2_imwrite_unicode(preview_path, preview)
```

**前端加载策略**：
```javascript
// 默认加载预览图
fetch('/TIE/api/review/image/<file>?preview=1')
// 自动按比例换算标注坐标
const scale = previewSize / imageSize;
annotation.box = annotation.box.map(v => v * scale);
```

### 2️⃣ JSON 缓存禁用
```python
def _no_cache_json_response(payload, status=200):
    """标注 JSON 文件常变，必须禁止缓存"""
    resp = jsonify(payload)
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    resp.status_code = status
    return resp
```

### 3️⃣ 数据库查询优化
```python
# 使用 index 加速常见查询
class User(db.Model):
    username = db.Column(db.String(64), unique=True, index=True)
    email = db.Column(db.String(120), unique=True, index=True)
```

### 4️⃣ 流式 LLM 调用
```python
# 流式处理，逐块输出，不用等待全部完成
chat_completion = client.chat.completions.create(
    ...,
    stream=True,  # ← 流式模式
)

for chunk in chat_completion:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

---

## 🐛 常见问题 & 排查

| 问题         | 症状               | 原因                                      | 解决                                         |
| ------------ | ------------------ | ----------------------------------------- | -------------------------------------------- |
| 上传超时     | 大文件上传时 502   | 超过 `MAX_CONTENT_LENGTH` 或 LLM 调用太慢 | 增加 timeout，分片上传                       |
| 中文路径失败 | 中文文件名保存失败 | `cv2.imwrite()` 编码问题                  | 使用 `imencode + open()`                     |
| 坐标错乱     | 标注框位置不对     | 预览图和原图比例不一致                    | 确保 `image_size` 和 `preview_size` 正确记录 |
| 内存溢出     | 大 PDF 处理时 OOM  | 一次性加载所有页到内存                    | 逐页处理或分片加载                           |
| LLM 超时     | 请求挂起           | API 响应慢或网络不稳定                    | 增加超时时间，重试机制                       |
| 标注不保存   | 保存后刷新消失     | 前端和后端坐标换算不一致                  | 调试 `_review_source` 字段                   |

---

## 📚 快速参考

### 环境变量（可选）

```bash
export FLASK_DEBUG=1              # 调试模式
export FLASK_APP=app.py           # 指定应用文件
export DATABASE_URL=sqlite://...  # 数据库连接（可选）
```

### 启动开发服务器

```bash
python app.py
# 或
flask run --host 0.0.0.0 --port 5000
```

### 访问地址

```
http://localhost:5000/TIE/              # 首页
http://localhost:5000/TIE/login         # 登录
http://localhost:5000/TIE/intelligent-analysis  # 上传
http://localhost:5000/TIE/data-review   # 复核
http://localhost:5000/TIE/admin/users   # 用户管理（超管）
```

### 常用 API 端点

```bash
# 上传文件
curl -X POST http://localhost:5000/TIE/upload \
  -F "file=@document.pdf" \
  -F "doc_type=1" \
  -F "target_name=张三"

# 获取可复核文件
curl http://localhost:5000/TIE/api/review/files \
  -H "Authorization: Bearer <token>"

# 保存复核
curl -X POST http://localhost:5000/TIE/api/review/save \
  -H "Content-Type: application/json" \
  -d '{"filename": "file.review.json", "annotations": {"info": [...]}}'
```

---

## 总结

本项目是一个完整的 **Web 版智能文档解析系统**，核心工作流为：

1. **上传** → PDF/图片 → 保存到用户目录
2. **解析** → LLM 提取字段 → 绘制标注 → 生成 JSON + JPG
3. **复核** → 前端 Fabric.js 交互编辑 → 保存结果
4. **导出** → 标注图片 → 打包下载

重点关注：
- ✅ 路径穿越防护（安全第一）
- ✅ 中文路径支持（用户友好）
- ✅ 预览图优化（性能优先）
- ✅ 坐标一致性（功能准确）
- ✅ 权限管理（访问控制）

