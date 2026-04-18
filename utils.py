#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档处理服务
集成 PySide6 应用中的 PDF 和图像处理功能
"""

import os
import sys
import json
from datetime import datetime
from PIL import Image
import numpy as np
import base64
import io
import json
import os
import re
import time
import cv2
import numpy as np
from openai import OpenAI
import requests
from PIL import Image, ImageDraw, ImageFont
import fitz  # PyMuPDF


def cv2_imwrite_unicode(path: str, img) -> None:
    """
    将 BGR 图像写入磁盘。OpenCV 的 cv2.imwrite 在部分 Linux 上对含中文等非 ASCII 路径会静默失败或异常，
    改用 imencode + Python 二进制写入，与路径编码无关。
    """
    ext = os.path.splitext(path)[1].lower() or '.jpg'
    if ext in ('.jpg', '.jpeg'):
        ok, buf = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    elif ext == '.png':
        ok, buf = cv2.imencode('.png', img)
    else:
        ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise OSError(f'图像编码失败: {path!r}')
    with open(path, 'wb') as f:
        f.write(buf.tobytes())


def get_chinese_font(size=20):
    import platform
    
    # 获取操作系统类型
    system = platform.system()  # 返回 'Windows', 'Linux', 'Darwin' 等
    
    if system == 'Windows':
        # Windows 系统中文字体候选列表
        font_candidates = [
            # Windows 常用中文字体路径
            "C:\\Windows\\Fonts\\simhei.ttf",      # 黑体（最常用）
            "C:\\Windows\\Fonts\\simsun.ttc",     # 宋体
            "C:\\Windows\\Fonts\\simkai.ttf",     # 楷体
            "C:\\Windows\\Fonts\\simfang.ttf",    # 仿宋
            "C:\\Windows\\Fonts\\msyh.ttc",       # 微软雅黑
            "C:\\Windows\\Fonts\\msyhbd.ttc",     # 微软雅黑 Bold
        ]
        
        for font_path in font_candidates:
            if os.path.exists(font_path):
                try:
                    # Windows 的 TTC 文件需要指定 index
                    if font_path.endswith('.ttc'):
                        return ImageFont.truetype(font_path, size, index=0)
                    else:
                        return ImageFont.truetype(font_path, size)
                except Exception as e:
                    print(f"字体加载失败 {font_path}: {e}")
                    continue
        
        # 如果所有字体都失败，尝试默认字体
        print("未找到可用的中文字体，使用默认字体")
        return ImageFont.load_default()
    
    else:
        # Linux/Ubuntu 系统中文字体候选列表
        font_candidates = [
            # Ubuntu 常用中文字体路径
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",  # 文泉驿微米黑
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",  # Noto 字体
            "/usr/share/fonts/truetype/arphic/ukai.ttc",  # AR PL UMing
            "/usr/share/fonts/truetype/arphic/uming.ttc",
        ]
        
        for font_path in font_candidates:
            if os.path.exists(font_path):
                try:
                    return ImageFont.truetype(font_path, size, index=0)
                except:
                    continue
        
        # 如果没有找到，尝试安装
        print("正在安装文泉驿中文字体...")
        os.system("sudo apt-get update && sudo apt-get install fonts-wqy-microhei -y")
        
        if os.path.exists("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"):
            return ImageFont.truetype("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", size)
        
        # 最后尝试默认字体
        return ImageFont.load_default()

# 使用
font = get_chinese_font(20)

def extract_outermost_braces(text):
    """提取最外层的大括号内容，支持嵌套"""
    
    result = []
    stack = []
    start = -1
    
    for i, char in enumerate(text):
        if char == '{':
            if not stack:  # 最外层开始
                start = i
            stack.append('{')
        elif char == '}':
            if stack:
                stack.pop()
                if not stack:  # 最外层结束
                    result.append(text[start:i+1])
    
    return result

def str_to_json(text):
    """从字符串提取并转换为JSON"""
    
    json_strings = extract_outermost_braces(text)
    
    for json_str in json_strings:
        try:
            data = json.loads(json_str)
            return data
        except json.JSONDecodeError:
            # 如果JSON格式有问题，尝试修复常见问题
            try:
                # 修复单引号
                json_str = json_str.replace("'", '"')
                # 修复无引号的键
                json_str = re.sub(r'(\w+)(?=\s*:)', r'"\1"', json_str)
                
                data = json.loads(json_str)
                return data
            except:
                continue
    
    return None
def encode_image_from_memory(image: Image.Image) -> str:
    """**内存中的图片直接编码Base64，不存文件**"""
    buffer = io.BytesIO()
    # 直接把PIL图片保存到内存缓冲区
    image.save(buffer, format='JPEG')
    # 从内存读取并编码
    return base64.b64encode(buffer.getvalue()).decode("utf-8")
def image_to_base64(img, format='JPEG'):
    buffered = io.BytesIO()
    img.save(buffered, format=format)
    img_base64 = base64.b64encode(buffered.getvalue()).decode()
    # 必须加这个前缀！！！
    return f"data:image/jpeg;base64,{img_base64}"
    return img_base64

def prosses_file(file_path):
    with open(file_path, "rb") as file:
        file_bytes = file.read()
        file_data = base64.b64encode(file_bytes).decode("ascii")
    return file_data
def post_box_info(images,api_key,API_URL):
    input_image = None
    if isinstance(images, str):
        input_image = prosses_file(images)
    else:
        input_image = encode_image_from_memory(images)
    headers = {
        "Authorization": f"token {api_key}",
        "Content-Type": "application/json"
    }

    required_payload = {
        "file": input_image,
        "fileType": 1 ,  # For PDF documents, set `fileType` to 0; for images, set `fileType` to 1
    }

    optional_payload = {
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useTextlineOrientation": False,
        "useChartRecognition": False,
    }

    payload = {**required_payload, **optional_payload}
    
    response = requests.post(API_URL, json=payload, headers=headers)
    # assert response.status_code == 200
    if response.status_code != 200:

        return None,None
    result = response.json()["result"]
    image_det = result['layoutParsingResults'][0]['outputImages']['layout_det_res']
    bboxs = result['ocrResults'][0]['prunedResult']['rec_boxes']
    info = result['ocrResults'][0]['prunedResult']['rec_texts']
    return bboxs, info,image_det

def clear_info(result2):
    # 清洗LLM返回结果
    result2 = result2.strip().replace("`", "").replace("\n", "").replace("json", "")
    try:
        result2 = json.loads(result2)
        # 校验返回值是否为数组
        if not isinstance(result2, list):
            print(f"错误: LLM返回值格式异常，需为JSON数组，实际为: {type(result2)}")
            return None
        return result2
    except json.JSONDecodeError as e:
        print(f"错误: LLM返回值解析失败，格式异常: {e}")
        print(f"LLM原始返回值: {result2}")
        return None
def draw_annotations_with_image(image_pil, result2, output_path="Parsed_PDF_Visualization.png",thickness=2):
    # 绘制数据
    image_cv2 = np.array(image_pil)
    image_cv2_bgr = cv2.cvtColor(image_cv2, cv2.COLOR_RGB2BGR)  
    for item in result2:
        # 校验必填字段
        required_fields = ["title", "box","内容", "标红"]
        if not all(field in item for field in required_fields):
            print(f"警告: 数组元素缺失必填字段，跳过该元素: {item}")
            continue

        # 获取核心信息
        title = item["title"]  # 信息类型：人才姓名、著作名称、出版商、出版国家、出版年份
        # box_title = item["box_title"]
        # box_info = item["box_info"]
        content = title + ": "+ item["内容"]
        is_red = item["标红"]
        merged_box = item["box"]
        # 4. 绘制标注（统一视觉规则）
        if is_red:
            # 绘制红框
            cv2.rectangle(image_cv2_bgr, (merged_box[0], merged_box[1]), (merged_box[2], merged_box[3]), (0, 0, 255), thickness)
        else:
            # 绘制蓝框
            cv2.rectangle(image_cv2_bgr, (merged_box[0], merged_box[1]), (merged_box[2], merged_box[3]), (255, 0, 0), thickness)
        # 绘制文本
        text_x = merged_box[0] + 5
        text_y = merged_box[1] + 5
        # 人才姓名用青色文字，其他信息用红色文字
        text_color = (255, 0, 0) if title == "人才姓名" else (0, 255, 255)
        image_cv2_bgr = draw_chinese_text(image_cv2_bgr, content, (text_x, text_y), font_size=50, color=text_color, thickness=thickness)
        cv2_imwrite_unicode(output_path, image_cv2_bgr)


        
def llm_post(
    client,
    model_name,
    prompt,
    image=None,
    system_prompt="你是专业的证件解析助手",
    max_token=1024,
    chat_history=None,
    progress_callback=None
):
    if chat_history is None:
        chat_history = []

    # ========== 构造当前用户输入（文本 + 图片 多模态） ==========
    user_content = [{"type": "text", "text": prompt}]
    if image is not None:
        if isinstance(image, str):
            user_content.insert(0, {"type": "image_url", "image_url": {"url": image}})
        elif isinstance(image, list):
            for i in image:
                user_content.append({"type": "image_url", "image_url": {"url": i}})

    # ========== 构建完整消息 ==========
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(chat_history)
    messages.append({"role": "user", "content": user_content})

    # ========== 流式调用 ==========
    chat_completion = client.chat.completions.create(
        model=model_name,
        messages=messages,
        stream=True,
        extra_body={"penalty_score": 1},
        max_completion_tokens=max_token,
        temperature=0.8,
        top_p=0.85,
        frequency_penalty=0,
        presence_penalty=0
    )

    # ====================== 【关键修复】分开存储 ======================
    reasoning_text = ""  # 思考过程（仅打印，不返回）
    final_result = ""    # 最终正式回答（返回这个）

    for chunk in chat_completion:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta

        # 1. 思考内容：只打印，不进结果
        if hasattr(delta, "reasoning_content") and delta.reasoning_content:
            print(delta.reasoning_content, end="", flush=True)
            reasoning_text += delta.reasoning_content
        # 2. 正式回答：只收集这个到 result
        elif delta.content:
            print(delta.content, end="", flush=True)
            final_result += delta.content

    # ========== 更新历史：只存正式回答，不存思考 ==========
    chat_history.append({"role": "user", "content": prompt})
    chat_history.append({"role": "assistant", "content": final_result})

    # ✅ 返回：只有干净的答案
    return final_result, chat_history




def draw_chinese_text(image, text, position, font_size=20, color=(255, 255, 255), thickness=2):
    """在OpenCV图像上绘制中文文本"""
    if not text:  # 如果文本为空，直接返回原图
        return image
    
    # OpenCV图像转换为PIL图像
    pil_image = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_image)
    
    # 获取中文字体
    font = get_chinese_font(font_size)
    
    # 绘制中文文本
    draw.text(position, text, font=font, fill=color)
    
    # PIL图像转回OpenCV格式
    image_with_text = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
    return image_with_text



def convert_from_path(pdf_path, zoom=4.0):
    """
    【完全兼容 pdf2image.convert_from_path】
    纯内存操作，不保存任何文件，直接返回 PIL.Image 对象列表
    :param pdf_path: PDF文件路径
    :param zoom: 缩放因子（控制清晰度，默认2.0）
    :return: List[PIL.Image.Image]  和原函数输出一模一样
    """
    # 存储PIL图像的列表（和convert_from_path返回值完全一致）
    pil_images = []
    
    # 打开PDF
    doc = fitz.open(pdf_path)
    # 遍历每一页
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        # 设置缩放（提高图片清晰度）
        mat = fitz.Matrix(zoom, zoom)
        # 生成页面像素图
        pix = page.get_pixmap(matrix=mat)
        
        # 核心：PyMuPDF像素图 → 转换为 PIL Image 对象（纯内存，无文件）
        pil_img = Image.open(io.BytesIO(pix.tobytes()))
        pil_images.append(pil_img)
    
    # 关闭PDF文档
    doc.close()
    return pil_images


def merge_llm_post(file_path: str, check_class: str, name: str = "", model_name="qwen-vl-max", api_key="", base_url="", progress_callback=None):
    start = time.time()
    save_roots = os.path.dirname(file_path)
    file_stem = os.path.splitext(os.path.basename(file_path))[0]
    # 服务器上进程的工作目录可能不是项目根，prompt/ 用绝对路径更稳
    _here = os.path.abspath(os.path.dirname(__file__))
    _prompt_dir = os.path.join(_here, "prompt")
    client =  OpenAI(
                api_key=api_key,
                base_url=base_url,
            )
    # 清理res
    history = []
    image_input = []
    image_saves =  []
    image_save_resize =  []
    sizes = []
    with open(os.path.join(_prompt_dir, 'system.md'), "r", encoding="utf-8") as f:
        system_prompt = f.read()
    with open(os.path.join(_prompt_dir, f"{check_class}.md"), "r", encoding="utf-8") as f:
        concent = f.read()
    if check_class != "1":    
        concent += f"我现在需要查找的人才姓名是:{name}"
    # 扩展名大小写不敏感：.PDF 也应按 PDF 处理
    if os.path.splitext(file_path)[1].lower() == ".pdf":
        image_list = convert_from_path(file_path)
    else:
        image_list = [Image.open(file_path)]
    for index,image in enumerate(image_list):
        w,h = image.size    
        sizes.append((w,h))
        image_resize = image.resize((1000,1000))
        image_input.append(image_to_base64(image_resize))
        image_cv = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        image_saves.append(image_cv)
        image_cv_resize = cv2.cvtColor(np.array(image_resize), cv2.COLOR_RGB2BGR)
        image_save_resize.append(image_cv_resize)

    result, history = llm_post(
        client=client,
        system_prompt=system_prompt,
        prompt=concent,
        model_name=model_name,
        image=image_input,
        chat_history=history,
        progress_callback=progress_callback
    )
    result = clear_info(result)
    try:    
        result = check_llm_result(client,f"我现在需要处理的信息是:{result}",model_name)
    except Exception as e:
        print(f"错误: 翻译失败: {e}")
        print(f"错误: 翻译失败: {result}")
        result = result
    # 第一步获取到了每个信息在哪一页。
    if isinstance(result, str):
        result = clear_info(result)
    save_p = []
    save_json = {}
    for j in result:
        # 将检测框 膨胀 10pix 并且不超过图像边界
        # 确保页码是整数（LLM 可能返回字符串）
        packge = int(j['页码']) if isinstance(j['页码'], str) else j['页码']
        save_p.append(packge)
        if packge-1 not in save_json:
            save_json[packge-1] = {'info':[]}
        write_image = image_saves[packge-1] 
        w,h = sizes[packge-1]
        if j['box']:
            # 将box坐标转换从1000x1000缩放回原图尺寸
            j["box"][0] = int(j["box"][0] / 1000 * w)
            j["box"][1] = int(j["box"][1] / 1000 * h)
            j["box"][2] = int(j["box"][2] / 1000 * w)
            j["box"][3] = int(j["box"][3] / 1000 * h)    
        print("Add save_json:",j)
        save_json[packge-1]['info'].append(j)
        print("add save_json success")
        print("add image_save")
        image_saves[packge-1] = write_image
        print("add image_save success")
    save_image_list = []
    save_p = set(save_p)
    for packge in save_p:   
        save_path = os.path.join(save_roots, file_stem + f"_{packge}.jpg")
        save_image_list.append(save_path)
        save_json_path = save_path.replace(".jpg", ".json")
        img_bgr = image_saves[packge-1]
        cv2_imwrite_unicode(save_path, img_bgr)

        # 生成预览图（复核页默认用预览图，显著减少前端 Fabric 渲染卡顿）
        try:
            h0, w0 = img_bgr.shape[:2]
            max_edge = 1600
            scale = min(1.0, float(max_edge) / float(max(w0, h0) or 1))
            pw = max(1, int(round(w0 * scale)))
            ph = max(1, int(round(h0 * scale)))
            if scale < 0.999:
                preview = cv2.resize(img_bgr, (pw, ph), interpolation=cv2.INTER_AREA)
            else:
                preview = img_bgr
            preview_path = save_path.replace(".jpg", ".preview.jpg")
            cv2_imwrite_unicode(preview_path, preview)
        except Exception as e:
            # 预览图失败不应影响主流程
            print(f"预览图生成失败({save_path}): {e}")
            pw = ph = None
            w0 = h0 = None

        json_data = save_json[packge-1]
        # 记录原图与预览图尺寸，供前端按比例缩放标注坐标
        if isinstance(json_data, dict):
            if w0 and h0:
                json_data["image_size"] = [int(w0), int(h0)]
            if pw and ph:
                json_data["preview_size"] = [int(pw), int(ph)]
        with open(save_json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=4)
        
        
    return save_image_list

def check_llm_result(client,concent,model_name):

    result, history = llm_post(
        client=client,
        system_prompt="""
        你需要检查用户的输入中是否存在 非简体中文数据
            - 如果有，那么你需要翻译简体中文并进行替换，最后按照输出格式输出。
            - 如果没有，那么你需要直接输出用户输入的json数组，不要进行任何修改。

        # 输出格式强制规范（零容错，严格匹配）
        1、必须输出纯JSON数组，数组内每个元素为一个字段条目，**每个条目必须包含且仅包含以下4个字段，字段名、字段顺序严格与示例一致**：
        ```json
        [
            {
                "title": "",     // 表示这是什么内容 如 人才姓名、国籍、论文题目 具体需要你就根据用户的需求查找填写。
                "box": [x1,y1,x2,y2],
                "内容": "严格符合翻译规则的标准简体中文，禁止留空",
                "标红": true/false
                "页码": int,     // 表示该条内容所在页码，从1开始
            }
        ]
        ```
        2、输出结果只是一个翻译，不可以有新增、删除等情况出现。
        3、当没有需要翻译的信息时，请直接输出用户输入的json数组，不要进行任何修改。
        """,
        prompt=concent,
        model_name=model_name,
        image=None,
        chat_history=[],
        progress_callback=None
    )
    return result