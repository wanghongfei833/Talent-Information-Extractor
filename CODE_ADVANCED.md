# 代码逻辑补充详解 - 关键细节

## 📌 文件上传处理详解

### 上传端点：`POST /upload`

```python
@tie.route('/upload', methods=['POST'])
@login_required
def upload_file():
```

#### 请求参数（Form Data）
```
file: <binary>              # 文件二进制数据
doc_type: string            # 文档类型（如 "1", "2", "4-1" 等）
target_name: string (可选)  # 目标姓名（检索人才时使用）
```

#### 处理流程详解

**第 1 步：文件名安全处理**
```python
filename = _safe_upload_basename_unicode(file.filename)
# 这个函数会：
# 1. 去掉路径穿越字符（.. / \）
# 2. 去掉控制字符和 Windows 非法字符（< > : " / \ | ? *）
# 3. 保留中文、日文等 Unicode 字符（不像 werkzeug.secure_filename 那样清空）
# 4. 避免 Windows 保留名（CON, PRN, AUX, COM1-9, LPT1-9）
# 5. 限制长度 ≤ 200 字符

if not filename:
    # 如果无法获得合法文件名，生成回退名
    ext = _safe_ext_from_original_for_fallback(file.filename)
    filename = f"upload_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
```

**第 2 步：创建用户目录并保存**
```python
filepath = os.path.join(app.config['UPLOAD_FOLDER'], str(user_id), save_filename)
dir_name = os.path.dirname(filepath)
os.makedirs(dir_name, exist_ok=True)  # 创建 uploads/<user_id>/ 目录
file.save(filepath)  # 保存上传文件到磁盘
```

**第 3 步：调用核心解析函数**
```python
image_list = merge_llm_post(
    file_path=filepath,        # 上传文件的完整路径
    check_class=doc_type,      # 文档类型（对应 prompt/<type>.txt）
    name=target_name,          # 目标姓名
    model_name=model_name,     # 用户配置的 LLM 模型
    api_key=api_key,          # 用户的 API Key
    base_url=base_url,        # LLM API 地址
    progress_callback=None    # 进度回调（暂未使用）
)
```

**第 4 步：清理并返回**
```python
# 删除原始上传文件（只保留解析产物）
os.remove(filepath)

return jsonify({
    'success': True,
    'filename': filename,         # 原文件名
    'save_filename': save_filename,
    'message': '文件上传成功'
})
```

#### 错误处理
```python
try:
    # ... 处理过程 ...
except Exception as e:
    # 回滚：删除已保存的文件
    if filepath and os.path.exists(filepath):
        os.remove(filepath)
    if json_save_path and os.path.exists(json_save_path):
        os.remove(json_save_path)
    for image_path in image_list:
        if os.path.exists(image_path):
            os.remove(image_path)
    
    return jsonify({'error': str(e)}), 500
```

---

## 🧠 LLM 交互详解

### 调用函数：`llm_post()`

```python
def llm_post(
    client,                      # OpenAI 客户端实例
    model_name,                  # 模型名（如 "qwen-vl-max"）
    prompt,                      # 用户提示词
    image=None,                  # 单张或多张图片（Base64 URL）
    system_prompt="...",         # 系统提示词
    max_token=1024,             # 最大输出 Token
    chat_history=None,          # 对话历史（多轮对话）
    progress_callback=None      # 进度回调
):
```

#### 构建请求

**多模态内容**：
```python
user_content = [{"type": "text", "text": prompt}]
if image is not None:
    if isinstance(image, str):
        # 单张图片
        user_content.insert(0, {
            "type": "image_url",
            "image_url": {"url": image}
        })
    elif isinstance(image, list):
        # 多张图片
        for img_url in image:
            user_content.append({
                "type": "image_url",
                "image_url": {"url": img_url}
            })
```

**消息序列**：
```python
messages = [
    {"role": "system", "content": system_prompt},   # 角色设定
]
messages.extend(chat_history)                        # 历史对话
messages.append({
    "role": "user",
    "content": user_content                         # 当前轮次：[图片, 文字]
})
```

**API 请求参数**：
```python
chat_completion = client.chat.completions.create(
    model=model_name,
    messages=messages,
    stream=True,                                    # 流式输出
    extra_body={"penalty_score": 1},               # 额外参数
    max_completion_tokens=1024,
    temperature=0.8,                               # 控制随机性（0-1，越小越确定）
    top_p=0.85,                                    # 核采样
    frequency_penalty=0,                           # 频率惩罚
    presence_penalty=0                             # 出现惩罚
)
```

#### 流式处理（支持思考过程）

某些 LLM（如 DeepSeek）支持输出「思考过程」（reasoning）和「最终答案」（content）的分离：

```python
reasoning_text = ""   # 思考过程（仅打印，不返回）
final_result = ""     # 最终答案（返回这个）

for chunk in chat_completion:
    if not chunk.choices:
        continue
    delta = chunk.choices[0].delta
    
    # 1. 思考内容（仅打印，不保存到返回值）
    if hasattr(delta, "reasoning_content") and delta.reasoning_content:
        print(delta.reasoning_content, end="", flush=True)
        reasoning_text += delta.reasoning_content
    
    # 2. 正式回答（这才是要返回的）
    elif delta.content:
        print(delta.content, end="", flush=True)
        final_result += delta.content

# 更新历史：只保存正式回答，不保存思考过程
chat_history.append({"role": "user", "content": prompt})
chat_history.append({"role": "assistant", "content": final_result})

return final_result, chat_history
```

### 提示词加载与拼接

```python
# 读取系统提示词
with open(os.path.join(_prompt_dir, 'system.txt'), "r", encoding="utf-8") as f:
    system_prompt = f.read()

# 读取文档类型对应的提示词
with open(os.path.join(_prompt_dir, f"{check_class}.txt"), "r", encoding="utf-8") as f:
    content = f.read()

# 若需要检索特定人才，追加名字到提示词
if check_class != "1":
    content += f"我现在需要查找的人才姓名是:{name}"

# 调用 LLM
result, history = llm_post(
    client=client,
    system_prompt=system_prompt,
    prompt=content,
    model_name=model_name,
    image=image_input,
    chat_history=history
)
```

---

## 🖼️ 图像处理详解

### PDF 转图片：`convert_from_path()`

```python
def convert_from_path(pdf_path, zoom=4.0):
    """
    将 PDF 转为 PIL.Image 对象列表（纯内存操作，无中间文件）
    
    参数：
      - pdf_path: PDF 文件路径
      - zoom: 缩放因子（4.0 = 400% 清晰度）
    
    返回：
      - List[PIL.Image.Image]：每页一个 PIL 图象对象
    """
    pil_images = []
    
    doc = fitz.open(pdf_path)
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        
        # 设置缩放（提高清晰度）
        mat = fitz.Matrix(zoom, zoom)
        
        # 生成像素图
        pix = page.get_pixmap(matrix=mat)
        
        # 核心：PyMuPDF 像素图 → PIL Image（无文件中转）
        pil_img = Image.open(io.BytesIO(pix.tobytes()))
        pil_images.append(pil_img)
    
    doc.close()
    return pil_images
```

**为什么用 PyMuPDF 而不是 pdf2image**：
- `pdf2image.convert_from_path()` 依赖 Poppler，部署困难
- `PyMuPDF (fitz)` 是单一 C 库，部署更简单
- `convert_from_path()` 函数兼容原有接口，无需改代码

### 图片缩放与编码

```python
# 缩放到 1000×1000（便于 LLM 理解，减少 Token 用量）
image_resize = image.resize((1000, 1000))

# 转为 Base64（作为 data URL 传递给 LLM）
image_to_base64(image_resize)
# 返回：data:image/jpeg;base64,/9j/4AAQSkZJR...
```

### 坐标变换（关键！）

**问题**：LLM 看到的是 1000×1000 缩放图，识别出的坐标是相对这个尺寸的。但我们需要将坐标还原到原图。

**解决**：
```python
# 原图尺寸
w, h = sizes[page_idx]  # 例：[1920, 2560]

# LLM 返回的坐标（相对 1000×1000）
box_1000 = [100, 50, 300, 80]

# 还原到原图坐标
box_original = [
    int(box_1000[0] / 1000 * w),  # x1: 100 / 1000 * 1920 = 192
    int(box_1000[1] / 1000 * h),  # y1: 50 / 1000 * 2560 = 128
    int(box_1000[2] / 1000 * w),  # x2: 300 / 1000 * 1920 = 576
    int(box_1000[3] / 1000 * h)   # y2: 80 / 1000 * 2560 = 204
]
# 最终：[192, 128, 576, 204]
```

### 图像标注与绘制

```python
def draw_annotations_with_image(image_pil, result, output_path):
    """在 PIL 图像上绘制标注框和文本"""
    
    # PIL → OpenCV 格式（RGB → BGR）
    image_cv = np.array(image_pil)
    image_cv_bgr = cv2.cvtColor(image_cv, cv2.COLOR_RGB2BGR)
    
    for item in result:
        title = item["title"]           # "人才姓名"
        box = item["box"]               # [x1, y1, x2, y2]
        content = title + ": " + item["内容"]
        is_red = item["标红"]
        
        # 1. 绘制矩形框
        color = (0, 0, 255) if is_red else (255, 0, 0)  # BGR: 红或蓝
        cv2.rectangle(image_cv_bgr, 
                     (box[0], box[1]),
                     (box[2], box[3]),
                     color, thickness=2)
        
        # 2. 绘制中文文本（需要特殊处理）
        text_x = box[0] + 5
        text_y = box[1] + 5
        text_color = (255, 0, 0) if title == "人才姓名" else (0, 255, 255)
        
        image_cv_bgr = draw_chinese_text(
            image_cv_bgr, content,
            (text_x, text_y),
            font_size=50, color=text_color
        )
    
    # 3. 写入文件（支持中文路径）
    cv2_imwrite_unicode(output_path, image_cv_bgr)
```

### 中文字体加载（跨平台）

```python
def get_chinese_font(size=20):
    """自动选择系统可用的中文字体"""
    system = platform.system()  # 'Windows', 'Linux', 'Darwin'
    
    if system == 'Windows':
        font_candidates = [
            "C:\\Windows\\Fonts\\simhei.ttf",      # 黑体
            "C:\\Windows\\Fonts\\simsun.ttc",      # 宋体
            "C:\\Windows\\Fonts\\msyh.ttc",        # 微软雅黑
        ]
    else:  # Linux/macOS
        font_candidates = [
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        ]
    
    for font_path in font_candidates:
        if os.path.exists(font_path):
            try:
                # TTC 文件需要指定 index=0
                if font_path.endswith('.ttc'):
                    return ImageFont.truetype(font_path, size, index=0)
                else:
                    return ImageFont.truetype(font_path, size)
            except:
                continue
    
    # 都失败，使用默认字体
    return ImageFont.load_default()
```

### Unicode 安全的文件写入

```python
def cv2_imwrite_unicode(path: str, img) -> None:
    """
    OpenCV 的 cv2.imwrite() 在某些 Linux 环境下
    对含中文等非 ASCII 的路径会静默失败。
    
    改用 imencode + 二进制写，规避编码问题。
    """
    ext = os.path.splitext(path)[1].lower() or '.jpg'
    
    # 编码为二进制
    if ext in ('.jpg', '.jpeg'):
        ok, buf = cv2.imencode('.jpg', img, 
                              [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    elif ext == '.png':
        ok, buf = cv2.imencode('.png', img)
    else:
        ok, buf = cv2.imencode(ext, img)
    
    if not ok:
        raise OSError(f'图像编码失败: {path!r}')
    
    # 二进制写入（与路径编码无关）
    with open(path, 'wb') as f:
        f.write(buf.tobytes())
```

---

## 📋 JSON 数据清理

### 格式修复：`clear_info()`

```python
def clear_info(result_str):
    """修复 LLM 返回的 JSON 格式问题"""
    
    # 1. 去掉代码块标记
    result_str = result_str.strip()
    result_str = result_str.replace("`", "")
    result_str = result_str.replace("\n", "")
    result_str = result_str.replace("json", "")
    
    # 2. 尝试直接解析
    try:
        result = json.loads(result_str)
        # 3. 验证必须是数组
        if not isinstance(result, list):
            print(f"错误: LLM 返回值不是数组，而是 {type(result)}")
            return None
        return result
    except json.JSONDecodeError as e:
        # 4. 常见格式错误修复
        try:
            result_str = result_str.replace("'", '"')  # 单引号 → 双引号
            result_str = re.sub(r'(\w+)(?=\s*:)', r'"\1"', result_str)  # 无引号键
            result = json.loads(result_str)
            if isinstance(result, list):
                return result
        except:
            pass
        
        print(f"错误: JSON 解析失败")
        print(f"原始字符串: {result_str}")
        return None
```

### 翻译统一：`check_llm_result()`

```python
def check_llm_result(client, content, model_name):
    """二次调用 LLM，统一字段值的文字"""
    
    # 第二个系统提示词：翻译专家
    system_prompt = """
    你需要检查用户输入中是否存在非简体中文数据：
    - 有非中文 → 翻译为简体中文并替换
    - 都是中文 → 直接原样输出
    
    输出必须是标准 JSON 数组，每个元素包含 4 个字段：
    title, box, 内容, 标红, 页码
    """
    
    # 第二轮请求：输入是 LLM 第一次返回的结果
    result, _ = llm_post(
        client=client,
        system_prompt=system_prompt,
        prompt=content,  # 这里是上一步的 JSON 字符串
        model_name=model_name,
        image=None,      # 不需要图片了
        chat_history=[]
    )
    
    return result
```

---

## 💾 数据复核与保存

### 获取可复核文件列表

```python
@tie.route('/api/review/files')
@login_required
def get_review_files():
    user_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(current_user.id))
    
    files = []
    # 扫描 JPG 和 PNG 文件（跳过预览图）
    for img_path in glob.glob(os.path.join(user_folder, '*.jpg')):
        filename = os.path.basename(img_path)
        
        # 预览图不作为独立的"可复核文件"展示
        if '.preview.' in filename:
            continue
        
        base_name = os.path.splitext(filename)[0]
        
        files.append({
            'name': base_name,                    # 文件主名（不含扩展名）
            'image': filename,                    # 图片文件名
            'json': f"{base_name}.json",          # 解析结果 JSON
            'review_json': f"{base_name}.review.json",  # 复核保存 JSON
            'has_json': os.path.isfile(...),     # 是否存在原 JSON
            'has_review_json': os.path.isfile(...),  # 是否存在复核 JSON
        })
    
    files.sort(key=lambda x: x['name'])
    return jsonify({'files': files})
```

### 获取标注数据（智能选择源）

```python
@tie.route('/api/review/annotations-for/<image_filename>')
@login_required
def get_review_annotations_for_image(image_filename):
    """
    同一个图片可能有两个 JSON：
    - xxx.json：LLM 原始输出（只读参考）
    - xxx.review.json：用户修改后的复核结果（实际使用）
    
    策略：取修改时间更新的一份（防止用户修改被覆盖）
    """
    user_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(current_user.id))
    stem = os.path.splitext(image_filename)[0]
    
    review_path = _review_file_in_user_dir(user_folder, f'{stem}.review.json')
    source_path = _review_file_in_user_dir(user_folder, f'{stem}.json')
    
    candidates = []
    if review_path and os.path.isfile(review_path):
        candidates.append((review_path, os.path.getmtime(review_path)))
    if source_path and os.path.isfile(source_path):
        candidates.append((source_path, os.path.getmtime(source_path)))
    
    if not candidates:
        return _no_cache_json_response({'error': '无标注 JSON'}, 404)
    
    # 选择最新的那份
    best_path = max(candidates, key=lambda x: x[1])[0]
    
    with open(best_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 补充原图和预览图尺寸（用于坐标换算）
    if not data.get('image_size'):
        img_path = _review_file_in_user_dir(user_folder, image_filename)
        if img_path and os.path.isfile(img_path):
            with Image.open(img_path) as im:
                data['image_size'] = list(im.size)  # [width, height]
    
    # 记录数据源（便于调试）
    data['_review_source'] = {
        'file': os.path.basename(best_path),
        'userId': current_user.id,
        'mtime': int(os.path.getmtime(best_path)),
    }
    
    return _no_cache_json_response(data)
```

### 保存复核结果

```python
@tie.route('/api/review/save', methods=['POST'])
@login_required
def save_review_data():
    """
    保存用户在复核编辑器中修改的标注
    """
    data = request.json or {}
    filename = data.get('filename')          # 保存目标文件名
    annotations = data.get('annotations')   # 标注数据
    
    # 验证
    if not filename or annotations is None:
        return jsonify({'error': '参数错误'}), 400
    
    # annotations 可能是：
    # - [{ title, box, ... }]  数组格式
    # - { info: [...], ... }   对象格式（含其他元数据）
    
    if isinstance(annotations, list):
        data_to_write = {'info': annotations}
    else:
        # 提取 info 数组并去掉内部的私有字段（_开头的）
        info = annotations.get('info')
        if not isinstance(info, list):
            return jsonify({'error': '对象格式须包含 info 数组'}), 400
        
        clean_info = []
        for item in info:
            if isinstance(item, dict):
                # 去掉前端私有字段（如 _id, _selected 等）
                clean_item = {k: v for k, v in item.items() 
                             if not k.startswith('_')}
                clean_info.append(clean_item)
            else:
                clean_info.append(item)
        
        data_to_write = {k: v for k, v in annotations.items() 
                        if k != 'info'}
        data_to_write['info'] = clean_info
    
    # 保存为 *.review.json（标志着是复核后的结果）
    user_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(current_user.id))
    json_path = _review_file_in_user_dir(user_folder, filename)
    
    if not json_path:
        return jsonify({'error': '非法路径'}), 403
    
    # 保存
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data_to_write, f, ensure_ascii=False, indent=4)
    
    # 同步更新 *.json（保持一致性）
    if filename.lower().endswith('.review.json'):
        stem = _review_stem_from_json_filename(filename)
        source_path = _review_file_in_user_dir(user_folder, f'{stem}.json')
        
        if source_path:
            # 只保存 info 数组到 *.json，便于 IDE 查看
            info_only = data_to_write.get('info', [])
            with open(source_path, 'w', encoding='utf-8') as sf:
                json.dump({'info': info_only}, sf, ensure_ascii=False, indent=4)
    
    return jsonify({'success': True, 'message': '保存成功'})
```

---

## 📦 导出与下载

### 导出标注图片

```python
@tie.route('/api/review/export-jpg', methods=['POST'])
@login_required
def export_review_jpg():
    """
    前端在复核编辑器中完成标注后，
    调用 Canvas.toBlob() 生成 JPG，
    然后上传到这个端点保存。
    """
    user_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(current_user.id))
    image_name = request.form.get('image')  # 原始图片文件名
    file = request.files.get('file')        # 上传的 JPG 二进制
    
    # 验证
    if not _review_image_basename_ok(image_name):
        return jsonify({'error': '非法图片名'}), 400
    
    if not file:
        return jsonify({'error': '缺少上传文件'}), 400
    
    # 保存到 EXPORT 子目录
    export_dir = os.path.join(user_folder, 'EXPORT')
    os.makedirs(export_dir, exist_ok=True)
    
    stem = os.path.splitext(image_name)[0]
    out_path = os.path.join(export_dir, f'{stem}.jpg')
    
    data = file.read()
    
    # 简单的 JPG 校验（JPEG 头 FF D8）
    if not (len(data) >= 2 and data[0] == 0xFF and data[1] == 0xD8):
        return jsonify({'error': '不是有效的 JPG'}), 400
    
    with open(out_path, 'wb') as wf:
        wf.write(data)
    
    return jsonify({
        'success': True,
        'file': os.path.basename(out_path)
    })
```

### 打包下载

```python
@tie.route('/api/review/export-zip', methods=['POST'])
@login_required
def download_export_zip():
    """将多个导出 JPG 打包为 ZIP 下载"""
    
    data = request.json or {}
    images = data.get('images') or []  # 原始图片文件名列表
    
    user_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(current_user.id))
    export_dir = os.path.join(user_folder, 'EXPORT')
    
    if not os.path.isdir(export_dir):
        return jsonify({'error': 'EXPORT 目录不存在'}), 404
    
    # 内存中创建 ZIP
    buf = io.BytesIO()
    added = 0
    
    with zipfile.ZipFile(buf, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
        for img_name in images:
            if not isinstance(img_name, str):
                continue
            
            img_name = img_name.strip()
            if not _review_image_basename_ok(img_name):
                continue
            
            # 从 EXPORT/ 中寻找对应的 JPG
            stem = os.path.splitext(img_name)[0]
            export_jpg = os.path.join(export_dir, f'{stem}.jpg')
            
            if os.path.isfile(export_jpg):
                # 添加到 ZIP（以原始文件名作为包内路径）
                zf.write(export_jpg, arcname=os.path.basename(export_jpg))
                added += 1
    
    if added == 0:
        return jsonify({'error': '没有找到可导出的文件'}), 404
    
    buf.seek(0)
    filename = f'EXPORT_{datetime.now().strftime("%Y%m%d%H%M%S")}.zip'
    
    resp = send_file(
        buf,
        mimetype='application/zip',
        as_attachment=True,
        download_name=filename
    )
    
    # 禁止缓存
    resp.headers['Cache-Control'] = 'no-store, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    
    return resp
```

---

## 🔒 权限与访问控制

### 超级管理员判断

```python
def is_super_admin(self):
    """用户需同时满足两个条件"""
    return self.is_admin and self.level == 5
```

### 页面访问保护

```python
@tie.route('/admin/users')
@login_required
def manage_users():
    if not current_user.is_super_admin():
        flash('无权访问此页面', 'error')
        return redirect(url_for('tie.index'))
    
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('manage_users.html', users=users)
```

### API 访问保护

所有数据接口都使用 `@login_required` 装饰器：
```python
from flask_login import login_required, current_user

@tie.route('/api/review/files')
@login_required  # ← 未登录用户被拒绝
def get_review_files():
    user_id = current_user.id  # 获取当前用户
    # ...
```

---

## 📊 存储管理

### 获取存储占用

```python
def _dir_size_bytes(root_dir: str) -> int:
    """递归计算目录总大小"""
    total = 0
    if not os.path.isdir(root_dir):
        return 0
    
    for base, dirs, files in os.walk(root_dir):
        for name in files:
            fp = os.path.join(base, name)
            try:
                if not os.path.islink(fp):  # 跳过符号链接
                    total += os.path.getsize(fp)
            except OSError:
                continue  # 权限错误时忽略
    
    return total

@tie.route('/api/storage/usage')
@login_required
def tie_storage_usage():
    user_dir = os.path.join(app.config['UPLOAD_FOLDER'], str(current_user.id))
    used = _dir_size_bytes(user_dir)
    limit = 1024 * 1024 * 1024  # 1GB
    
    return jsonify({
        'user_id': current_user.id,
        'used_bytes': used,
        'limit_bytes': limit,
        'over_limit': used > limit
    })
```

### 清理存储

```python
@tie.route('/api/storage/clear', methods=['POST'])
@login_required
def tie_storage_clear():
    """删除用户目录下的所有文件（保留目录结构）"""
    user_dir = os.path.join(app.config['UPLOAD_FOLDER'], str(current_user.id))
    
    if not os.path.isdir(user_dir):
        return jsonify({'success': True, 'deleted_files': 0})
    
    deleted = 0
    freed = 0
    
    for base, dirs, files in os.walk(user_dir):
        for name in files:
            fp = os.path.join(base, name)
            try:
                if not os.path.islink(fp):
                    sz = os.path.getsize(fp)
                    os.remove(fp)
                    deleted += 1
                    freed += sz
            except OSError:
                continue  # 权限错误继续下一个
    
    return jsonify({
        'success': True,
        'deleted_files': deleted,
        'freed_bytes': freed
    })
```

---

## 🚨 错误处理与日志

### 数据库回滚

```python
@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()  # 发生服务器错误时回滚事务
    return render_template('errors/500.html'), 500
```

### 文件操作的异常处理

```python
try:
    # ... 文件操作 ...
    os.remove(filepath)
except OSError as e:
    print(f"文件删除失败: {e}")
    # 继续处理，不中断
```

### 日志输出

```python
print(f"\n{'='*60}")
print(f"【用户信息】")
print(f"  用户名：{username}")
print(f"  用户 ID: {user_id}")
print(f"【API 配置】")
print(f"  Model Name: {model_name}")
print(f"【文件信息】")
print(f"  文件名：{filename}")
print(f"  文件大小：{format_file_size(file_size)}")
print(f"{'='*60}\n")
```

