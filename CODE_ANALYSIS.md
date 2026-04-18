# 人才信息提取系统（TIE）- 代码逻辑详解

## 📋 项目概述
**Talent-Information-Extractor** 是一个基于Flask的Web应用，用于智能解析人才申报材料（PDF/图片）并进行可视化复核。系统集成大语言模型(LLM)进行字段抽取，支持人工二次复核和标注导出。

---

## 🏗️ 系统架构

```
用户请求
    ↓
Flask Web 应用 (app.py)
    ├─ 路由管理（Authentication, File Upload, API）
    ├─ 用户认证（Flask-Login）
    └─ 数据库操作（SQLAlchemy）
    ↓
业务核心 (utils.py)
    ├─ LLM 调用（OpenAI 兼容 API）
    ├─ PDF/图片处理（PyMuPDF, OpenCV, PIL）
    ├─ 图像标注与可视化
    └─ 文件I/O 与格式转换
    ↓
数据存储
    ├─ SQLite 数据库 (instance/app.db)
    ├─ 用户上传文件 (uploads/<user_id>/)
    └─ 解析结果 (.json, .jpg, .preview.jpg)
    ↓
前端呈现
    ├─ HTML 模板 (templates/)
    ├─ JavaScript (static/main.js)
    └─ CSS 样式 (static/style.css)
```

---

## 📁 核心文件说明

### 1️⃣ **models.py** - 数据模型
定义用户信息和权限系统：

```python
class User(UserMixin, db.Model):
    id                  # 用户ID（主键）
    username            # 用户名（唯一）
    email              # 邮箱（唯一）
    password_hash      # 密码哈希
    created_at         # 创建时间
    last_login         # 最后登录时间
    is_active          # 是否激活
    is_admin           # 是否管理员
    level              # 用户等级（1-5级）
    experience         # 经验值（用于升级）
    credits            # 积分
    api_key            # 用户的 API Key（管理员配置）
    base_url           # LLM API 地址
    model_name         # LLM 模型名称
```

**关键方法**：
- `set_password()` - 设置密码（哈希存储）
- `check_password()` - 验证密码
- `check_level_up()` - 检查升级条件

---

### 2️⃣ **app.py** - Flask 应用主程序

#### 🔑 配置部分
```python
TIE_PREFIX = '/TIE'                    # 路由前缀
MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 最大上传 500MB
ALLOWED_EXTENSIONS = {pdf, png, jpg, ...}  # 允许的文件类型
```

#### 🔐 路由分类

**1. 页面路由（GET）**
| 路由                               | 说明                     | 权限           |
| ---------------------------------- | ------------------------ | -------------- |
| `/`                                | 首页                     | 无需登录       |
| `/login`                           | 登录页                   | 无需登录       |
| `/register`                        | 用户注册（仅超级管理员） | 需要超级管理员 |
| `/dashboard`                       | 用户仪表板               | 需要登录       |
| `/intelligent-analysis`            | 智能解析页               | 需要登录       |
| `/data-review` 或 `/review-editor` | 数据复核编辑器           | 需要登录       |
| `/admin/users`                     | 用户管理                 | 需要超级管理员 |

**2. 文件上传与解析**
```
POST /upload
    ↓
验证文件（类型、大小）→ 保存到 uploads/<user_id>/
    ↓
merge_llm_post()（核心解析流程）
    ├─ PDF → 多页图片（PyMuPDF）
    ├─ 缩放图片 → Base64 编码
    ├─ 调用 LLM API 智能提取字段
    ├─ 解析结果 → 还原到原图坐标
    ├─ 绘制标注框 → 保存 JPG
    ├─ 生成预览图（长边≤1600px）
    └─ 保存为 JSON（含坐标信息）
    ↓
返回成功响应
```

**3. 数据复核 API**
```
GET  /api/review/files              # 获取用户可复核文件列表
GET  /api/review/image/<filename>   # 返回图片（优先返回预览图）
GET  /api/review/json/<filename>    # 返回标注JSON
GET  /api/review/annotations-for/<image_filename>  # 获取对应标注
POST /api/review/save               # 保存复核标注为 *.review.json
POST /api/review/export-jpg         # 导出标注后的JPG
POST /api/review/export-zip         # 打包下载导出文件
```

**4. 用户管理 API（超级管理员）**
```
POST /register                       # 创建新用户
GET  /admin/configure_user_api/<id>  # 配置用户 API
POST /admin/configure_user_api/<id>  # 保存 API 配置
```

**5. 存储管理**
```
GET  /api/storage/usage             # 获取用户存储占用（字节）
POST /api/storage/clear             # 清理用户所有文件
```

#### 🛡️ 安全机制

**路径穿越防护**：
```python
def _review_file_in_user_dir(user_folder, filename):
    # 确保文件路径在用户目录内
    # 检查 .. 和 / 等危险字符
    full_r = os.path.realpath(full)
    user_r = os.path.realpath(user_folder)
    if os.path.commonpath([full_r, user_r]) != user_r:
        return None  # 路径穿越！
```

**安全的文件名处理**：
```python
def _safe_upload_basename_unicode(original: str):
    # 保留中文等 Unicode 字符
    # 去掉路径穿越、控制字符、非法字符
    # 避免 Windows 保留名（CON, PRN, AUX 等）
```

---

### 3️⃣ **utils.py** - 核心业务逻辑

#### 🤖 LLM 调用流程

**① 初始化客户端**
```python
client = OpenAI(
    api_key=api_key,
    base_url=base_url  # 例：https://dashscope.aliyuncs.com/compatible-mode/v1
)
```

**② 多模态请求（文本 + 图片）**
```python
def llm_post(client, model_name, prompt, image=None, system_prompt="..."):
    user_content = [{"type": "text", "text": prompt}]
    if image:
        user_content.insert(0, {"type": "image_url", "image_url": {"url": image}})
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]
    
    # 流式调用
    chat_completion = client.chat.completions.create(
        model=model_name,
        messages=messages,
        stream=True,
        max_completion_tokens=1024,
        temperature=0.8,
        top_p=0.85
    )
    
    return final_result  # 仅返回正式答案，不返回思考过程
```

#### 📄 主解析函数（核心）

```python
def merge_llm_post(file_path, check_class, name, model_name, api_key, base_url):
    """
    完整解析流程
    
    输入：
      - file_path: 上传的 PDF/图片路径
      - check_class: 文档类型（对应 prompt/<class>.txt 文件）
      - name: 目标姓名（仅 check_class != "1" 时需要）
      - model_name: LLM 模型名
      - api_key: API Key
      - base_url: API 地址
    
    处理步骤：
      1️⃣ PDF 转图片 或 直接打开图片
         └─ 使用 PyMuPDF（fitz）：convert_from_path()
      
      2️⃣ 图片缩放 + Base64 编码
         └─ 1000×1000 缩放便于 LLM 理解，后续还原坐标
      
      3️⃣ 调用 LLM 提取字段
         ├─ 系统提示词：prompt/system.txt
         ├─ 用户提示词：prompt/<check_class>.txt
         └─ 返回 JSON 数组：[{title, box, 内容, 标红, 页码}, ...]
      
      4️⃣ 清理 LLM 结果
         ├─ 修复 JSON 格式错误
         ├─ 二次调用 LLM 进行翻译统一
         └─ 验证必填字段
      
      5️⃣ 坐标变换 + 标注绘制
         ├─ 1000×1000 → 原图尺寸（根据 box 缩放）
         ├─ OpenCV 绘制矩形框（蓝框普通，红框重点）
         ├─ PIL 绘制中文文本标签
         └─ cv2_imwrite_unicode() 保存（兼容中文路径）
      
      6️⃣ 生成预览图
         ├─ 长边缩放到 ≤1600px（减少前端渲染卡顿）
         ├─ 记录原图尺寸和预览图尺寸
         └─ 前端加载预览图，坐标按比例换算
      
      7️⃣ 保存结果
         ├─ <stem>_1.jpg      # 原尺寸标注图
         ├─ <stem>_1.preview.jpg  # 预览图
         └─ <stem>_1.json     # 解析结果（含 box, 文字, 标红标志）
    
    返回：
      - save_image_list: 生成的所有 JPG 路径列表
    """
```

**关键数据结构**：
```json
{
  "info": [
    {
      "title": "人才姓名",      // 字段类型
      "box": [100, 50, 300, 80],  // [x1, y1, x2, y2] 矩形框坐标
      "内容": "张三",           // 提取的文本内容
      "标红": false,           // 是否标红（重点/异常）
      "页码": 1                // 所在页数
    }
  ],
  "image_size": [1920, 2560],   // 原图尺寸（用于坐标换算）
  "preview_size": [600, 800]    // 预览图尺寸（前端使用）
}
```

#### 🎨 图像处理函数

| 函数                            | 功能                                       |
| ------------------------------- | ------------------------------------------ |
| `convert_from_path(pdf_path)`   | PDF → 图片列表（内存处理，兼容 pdf2image） |
| `draw_annotations_with_image()` | 在图片上绘制标注框和文本                   |
| `cv2_imwrite_unicode()`         | OpenCV 写入（支持中文路径）                |
| `get_chinese_font()`            | 获取系统中文字体（Windows/Linux 自适应）   |
| `image_to_base64()`             | PIL 图片 → Base64 字符串                   |

#### ✅ 数据清理和验证

```python
def clear_info(result_str):
    """清洗 LLM 返回的 JSON 字符串"""
    # 去掉反引号、换行、json前缀
    # 修复单引号、无引号的键
    # 验证是否为 JSON 数组
    return json.loads(result_str)

def check_llm_result(client, content, model_name):
    """二次调用 LLM 进行翻译统一"""
    # 检查是否有非简体中文内容
    # 若有则翻译替换，无则直接返回
    return translated_result
```

---

## 🔄 核心业务流程

### 📤 上传与解析流程

```
用户上传文件 (POST /upload)
    ↓
验证权限（需要登录）
    ↓
验证文件（类型、大小）
    ↓
保存文件到 uploads/<user_id>/<filename>
    ↓
merge_llm_post() ────────────┐
    ├─ PDF 转图片            │
    ├─ 缩放 + Base64         │ 详见 utils.py
    ├─ LLM 提取              │ merge_llm_post()
    ├─ 坐标变换 + 绘制       │ 核心解析逻辑
    └─ 保存结果              │
                            ↓
生成输出文件：
    ├─ <stem>_1.jpg
    ├─ <stem>_1.preview.jpg
    └─ <stem>_1.json
    ↓
删除临时文件（原上传文件）
    ↓
返回成功响应
```

### 🔍 数据复核流程

```
用户访问 /data-review
    ↓
加载 GET /api/review/files （可复核文件列表）
    ↓
用户选择文件
    ↓
前端请求 GET /api/review/image/<filename>?preview=1
    ├─ 优先返回 <stem>.preview.jpg（减少渲染卡顿）
    └─ 自动加载 preview_size + image_size 用于坐标缩放
    ↓
前端请求 GET /api/review/annotations-for/<image>
    ├─ 查找 <stem>.review.json 或 <stem>.json
    ├─ 取修改时间更新的一份
    └─ 返回 {info, image_size, preview_size, _review_source}
    ↓
前端使用 Fabric.js 加载图片 + 标注框（可拖拽、编辑、删除）
    ↓
用户修改标注 → 前端实时渲染
    ↓
用户保存 POST /api/review/save
    ├─ 保存为 <stem>.review.json
    ├─ 同步更新 <stem>.json（保持一致性）
    └─ 返回 200 OK
    ↓
完成复核
```

### 📥 导出流程

```
用户在复核页渲染标注后的图片
    ↓
前端调用 Canvas.toBlob() 生成 JPG 二进制
    ↓
用户点击「导出」
    ↓
POST /api/review/export-jpg
    ├─ 接收前端上传的 JPG 二进制
    ├─ 保存到 uploads/<user_id>/EXPORT/<stem>.jpg
    └─ 返回文件名
    ↓
用户点击「批量下载」
    ↓
POST /api/review/export-zip
    ├─ 打包 EXPORT/ 目录下所有 JPG
    ├─ 生成 zip 文件
    └─ 返回 EXPORT_<timestamp>.zip
    ↓
用户下载完成
```

---

## 📊 文件存储结构

```
uploads/
  ├─ 1/  (user_id=1)
  │   ├─ 身份证_1.jpg              # 解析产物（原尺寸）
  │   ├─ 身份证_1.preview.jpg      # 预览图（长边≤1600px）
  │   ├─ 身份证_1.json             # 解析结果
  │   ├─ 身份证_1.review.json      # 复核保存结果
  │   ├─ 学位证_1.jpg
  │   ├─ 学位证_1.preview.jpg
  │   └─ EXPORT/                   # 导出目录
  │       ├─ 身份证_1.jpg          # 用户导出的标注图
  │       └─ 学位证_1.jpg
  │
  └─ 2/  (user_id=2)
      ├─ ...
      └─ EXPORT/
```

---

## 🧩 提示词系统（Prompt）

文件位置：`prompt/` 目录

| 文件                | 用途         | 说明                             |
| ------------------- | ------------ | -------------------------------- |
| `system.txt`        | 系统提示词   | 所有请求的基础角色设定           |
| `1.txt`             | 通用字段提取 | check_class="1"                  |
| `2.txt` ~ `5-6.txt` | 各类文档     | 针对身份证、学位证、论文、奖项等 |
| `step_start.txt`    | 流程启动     | （可能用于初始化）               |

**提示词结构**：
```
你是专业的证件解析助手...

用户需要你完成以下任务：
1. 从图片中提取以下字段...
2. 返回 JSON 数组格式...

输出示例：
[
  {
    "title": "...",
    "box": [...],
    "内容": "...",
    "标红": true/false,
    "页码": 1
  }
]
```

---

## 🔐 权限系统

### 用户等级（Level）

```
Level 1: 普通会员    (默认)
Level 2: 高级会员    (100+ 经验)
Level 3: VIP 会员    (500+ 经验)
Level 4: 超级 VIP    (2000+ 经验)
Level 5: 管理员      (10000+ 经验，is_admin=True)
```

### 功能权限

| 功能          | 普通用户 | 管理员 |
| ------------- | -------- | ------ |
| 上传和解析    | ✅        | ✅      |
| 数据复核      | ✅        | ✅      |
| 修改自己密码  | ✅        | ✅      |
| 查看用户列表  | ❌        | ✅      |
| 创建/删除用户 | ❌        | ✅      |
| 配置用户 API  | ❌        | ✅      |

---

## 🚀 启动流程

```python
if __name__ == '__main__':
    with app.app_context():
        # 1. 创建数据库表（首次运行）
        db.create_all()
        
        # 2. 创建超级管理员（如果不存在）
        #    用户名：admin
        #    密码：admin123!
        
        # 3. 启动 Flask 服务
        app.run(debug=True, host='0.0.0.0', port=5000)
```

访问地址：`http://localhost:5000/TIE/`

---

## 🛠️ 关键技术栈

| 层次         | 技术                   | 用途                  |
| ------------ | ---------------------- | --------------------- |
| **后端框架** | Flask                  | Web 应用框架          |
| **数据库**   | SQLAlchemy + SQLite    | ORM 和轻量级数据存储  |
| **用户认证** | Flask-Login            | 会话管理              |
| **LLM 集成** | OpenAI API（兼容接口） | 阿里云通义千问        |
| **图像处理** | OpenCV + PIL + PyMuPDF | PDF 转图、标注绘制    |
| **前端**     | Jinja2 + Fabric.js     | 模板渲染 + 交互式标注 |
| **文件操作** | zipfile + 二进制读写   | 导出和压缩            |

---

## ⚠️ 重要设计细节

### 1️⃣ 预览图机制
- **为什么**：原始 OCR 产物可能很大（2000×3000px），Fabric.js 直接渲染会卡顿
- **解决**：生成长边≤1600px 的预览图
- **坐标处理**：
  - 用户在预览图上标注 → 坐标缩放回原图 → 保存
  - 下次打开时，从预览图加载，但保存时用原坐标

### 2️⃣ LLM 二次调用
```
第一次调用：提取字段 → 返回 JSON
    ↓
第二次调用：翻译统一 → 确保中文统一
```

### 3️⃣ 复核 JSON 的两份机制
- `<stem>.json`：LLM 直接返回的解析结果（只读参考）
- `<stem>.review.json`：用户复核后保存的结果（实际使用）
- 若两者都存在，取修改时间更新的一份（防止覆盖）

### 4️⃣ 中文路径支持
- 普通 OpenCV `cv2.imwrite()` 在部分 Linux 上会失败
- **改进**：`cv2.imencode()` + `open(..., 'wb')` 规避路径编码问题

### 5️⃣ 路径穿越防护
```python
# ❌ 错误示范（危险）
file_path = os.path.join(user_dir, user_input)
# 若 user_input = "../../etc/passwd"，可以访问系统文件

# ✅ 正确做法
real_path = os.path.realpath(file_path)
user_real = os.path.realpath(user_dir)
if os.path.commonpath([real_path, user_real]) != user_real:
    return None  # 非法访问！
```

---

## 📝 工作流小结

```
┌─────────────┐
│  用户上传   │
└──────┬──────┘
       │
       ▼
┌─────────────────────────┐
│ 1. 文件保存             │
│ 2. PDF 转图 + 缩放      │
│ 3. LLM 提取字段        │
│ 4. 坐标变换 + 绘制     │
│ 5. 生成预览图          │
│ 6. 保存 JSON + JPG     │
└──────┬──────────────────┘
       │
       ▼
┌──────────────────┐
│  用户复核编辑   │◄─────┐
│  (Fabric.js)    │      │
└──────┬───────────┘      │
       │                  │
       ▼                  │
  ┌──────────┐            │
  │ 修改标注？│            │
  └┬────────┬┘            │
   │是      │否           │
   │        └────┐        │
   ▼             │        │
┌─────────┐      │    ┌────────┐
│ 保存    │      │    │  导出  │
│review  │      │    │  下载  │
│.json   │      │    └────────┘
└─────────┘      │
                 └───────────────┘
```

---

## 🎯 快速导航

- **添加新的文档类型**：创建 `prompt/<类型>.txt` 文件
- **修改 LLM 提示词**：编辑 `prompt/system.txt` 和对应类型文件
- **增加新功能**：在 `app.py` 中添加路由和处理逻辑
- **前端修改**：编辑 `templates/` 和 `static/` 中的文件
- **用户管理**：超级管理员访问 `/TIE/admin/users`

---

## 💡 常见问题诊断

| 问题             | 原因                            | 解决方案                                |
| ---------------- | ------------------------------- | --------------------------------------- |
| 服务器上传 500   | 工作目录导致 `prompt/` 路径失败 | 使用绝对路径（已修复）                  |
| 中文路径写入失败 | OpenCV 在 Linux 上编码问题      | 使用 `imencode + open()` （已修复）     |
| 标注坐标错乱     | 预览图和原图比例不匹配          | 同步记录 `image_size` 和 `preview_size` |
| 复核页加载慢     | 加载大图直接渲染                | 优先加载预览图（已优化）                |

