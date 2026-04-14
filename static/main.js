// 主 JavaScript 文件

let selectedFiles = []; // 存储选中的文件

document.addEventListener('DOMContentLoaded', function() {
    console.log('图像标注平台已加载');
    
    // 自动隐藏警告消息
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(function(alert) {
        setTimeout(function() {
            alert.style.transition = 'opacity 0.5s';
            alert.style.opacity = '0';
            setTimeout(function() {
                alert.style.display = 'none';
            }, 500);
        }, 5000);
    });
    
    // 初始化：只启用单文件上传，禁用其他
    disableOtherInputs('single');
    
    // 模式切换
    const modeBtns = document.querySelectorAll('.mode-btn');
    const fileAreas = {
        'single': document.getElementById('single-file-area'),
        'multiple': document.getElementById('multiple-file-area'),
        'folder': document.getElementById('folder-file-area')
    };
    
    modeBtns.forEach(btn => {
        btn.addEventListener('click', function() {
            // 移除所有激活状态
            modeBtns.forEach(b => b.classList.remove('active'));
            Object.values(fileAreas).forEach(area => area.classList.remove('active'));
            
            // 激活当前选择
            this.classList.add('active');
            const mode = this.dataset.mode;
            fileAreas[mode].classList.add('active');
            
            // 清空文件选择并禁用其他 input
            clearAllFiles();
            disableOtherInputs(mode);
        });
    });
    
    // 单文件上传处理
    const singleFileInput = document.getElementById('file');
    const singleFilePreview = document.getElementById('single-file-preview');
    if (singleFileInput && singleFilePreview) {
        singleFileInput.addEventListener('change', function(e) {
            const file = e.target.files[0];
            if (file) {
                selectedFiles = [file];
                singleFilePreview.innerHTML = `
                    <div class="file-item">
                        <span class="file-icon">${getFileIcon(file.name)}</span>
                        <div class="file-info">
                            <div class="file-name">${file.name}</div>
                            <div class="file-size">${formatFileSize(file.size)}</div>
                        </div>
                    </div>
                `;
                updateSubmitButton();
            }
        });
    }
    
    // 多文件上传处理
    const multipleFilesInput = document.getElementById('multiple-files');
    const multipleFilesPreview = document.getElementById('multiple-files-preview');
    if (multipleFilesInput && multipleFilesPreview) {
        multipleFilesInput.addEventListener('change', function(e) {
            const files = Array.from(e.target.files);
            if (files.length > 0) {
                selectedFiles = files;
                let previewHTML = '';
                files.forEach((file, index) => {
                    previewHTML += `
                        <div class="file-item">
                            <span class="file-icon">${getFileIcon(file.name)}</span>
                            <div class="file-info">
                                <div class="file-name">${file.name}</div>
                                <div class="file-size">${formatFileSize(file.size)}</div>
                            </div>
                        </div>
                    `;
                });
                multipleFilesPreview.innerHTML = previewHTML;
                updateSubmitButton();
            }
        });
    }
    
    // 文件夹上传处理
    const folderInput = document.getElementById('folder-input');
    const folderPreview = document.getElementById('folder-files-preview');
    if (folderInput && folderPreview) {
        folderInput.addEventListener('change', function(e) {
            const files = Array.from(e.target.files);
            if (files.length > 0) {
                selectedFiles = files;
                let previewHTML = '';
                let totalSize = 0;
                
                files.forEach((file, index) => {
                    previewHTML += `
                        <div class="file-item">
                            <span class="file-icon">${getFileIcon(file.name)}</span>
                            <div class="file-info">
                                <div class="file-name">${file.webkitRelativePath || file.name}</div>
                                <div class="file-size">${formatFileSize(file.size)}</div>
                            </div>
                        </div>
                    `;
                    totalSize += file.size;
                });
                
                folderPreview.innerHTML = previewHTML;
                updateSubmitButton();
            }
        });
    }
});

// 更新提交按钮状态
function updateSubmitButton() {
    const submitBtn = document.getElementById('submit-btn');
    const infoText = document.getElementById('selected-files-info');
    
    if (selectedFiles.length === 0) {
        submitBtn.disabled = true;
        infoText.innerHTML = '<span class="info-icon">ℹ️</span><span class="info-text">尚未选择任何文件</span>';
    } else {
        submitBtn.disabled = false;
        const totalSize = selectedFiles.reduce((sum, file) => sum + file.size, 0);
        infoText.innerHTML = `
            <span class="info-icon">✅</span>
            <span class="info-text">
                已选择 <strong>${selectedFiles.length}</strong> 个文件，
                总大小 <strong>${formatFileSize(totalSize)}</strong>
            </span>
        `;
    }
}

// 清空所有文件选择
function clearAllFiles() {
    selectedFiles = [];
    const inputs = ['file', 'multiple-files', 'folder-input'];
    inputs.forEach(id => {
        const input = document.getElementById(id);
        if (input) input.value = '';
    });
    
    const previews = ['single-file-preview', 'multiple-files-preview', 'folder-files-preview'];
    previews.forEach(id => {
        const preview = document.getElementById(id);
        if (preview) preview.innerHTML = '';
    });
    
    updateSubmitButton();
}

// 禁用其他模式的 input，只启用当前模式
function disableOtherInputs(currentMode) {
    const fileInput = document.getElementById('file');
    const multipleFilesInput = document.getElementById('multiple-files');
    const folderInput = document.getElementById('folder-input');
    
    // 先全部禁用
    if (fileInput) fileInput.disabled = true;
    if (multipleFilesInput) multipleFilesInput.disabled = true;
    if (folderInput) folderInput.disabled = true;
    
    // 只启用当前模式的 input
    if (currentMode === 'single' && fileInput) {
        fileInput.disabled = false;
    } else if (currentMode === 'multiple' && multipleFilesInput) {
        multipleFilesInput.disabled = false;
    } else if (currentMode === 'folder' && folderInput) {
        folderInput.disabled = false;
    }
}

// 获取文件图标
function getFileIcon(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    const icons = {
        'pdf': '📄',
        'png': '🖼️',
        'jpg': '🖼️',
        'jpeg': '🖼️',
        'bmp': '🖼️',
        'gif': '🖼️',
        'tiff': '🖼️',
        'webp': '🖼️'
    };
    return icons[ext] || '📄';
}

// 格式化文件大小
function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}
