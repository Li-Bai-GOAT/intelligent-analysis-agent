# -*- coding: utf-8 -*-
"""
文件管理 API

文件上传、下载、沙箱同步等
"""

import io
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, status, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.models.user import User
from app.api.deps import get_current_user
from app.services.file_service import FileService, SandboxFileService
from app.schemas.file import (
    FileUploadResponse,
    FileListResponse,
    SandboxBindingResponse,
    SandboxFileItem,
)
from app.repositories.file_repo import SandboxBindingRepository
import os
from datetime import datetime


router = APIRouter(prefix="/files", tags=["文件管理"])


@router.post("/upload", response_model=List[FileUploadResponse], summary="上传文件")
async def upload_files(
    files: List[UploadFile] = File(...),
    session_id: str = Query(..., description="关联的会话 ID（必填）"),
    user: User = Depends(get_current_user),
):
    """
    上传文件到会话关联的沙箱挂载目录。
    
    文件上传后自动在沙箱的 /workspace 目录可用，无需手动同步。
    单文件最大 100MB，超限文件会被跳过。
    """
    results = []
    for file in files:
        content = await file.read()
        if len(content) > 100 * 1024 * 1024:
            continue  # 跳过过大的文件
        
        user_file = await FileService.save_uploaded_file(
            user_id=str(user.id),
            file_content=content,
            original_name=file.filename,
            content_type=file.content_type,
            session_id=session_id,
        )
        results.append(FileUploadResponse(
            id=user_file.id,
            filename=user_file.filename,
            original_name=user_file.original_name,
            content_type=user_file.content_type,
            size=user_file.size,
            created_at=user_file.created_at,
        ))
    
    return results


@router.get("", response_model=List[FileListResponse], summary="获取文件列表")
async def list_files(
    session_id: Optional[str] = Query(None, description="按会话筛选"),
    user: User = Depends(get_current_user),
):
    """列出当前用户的所有上传文件，可按会话 ID 筛选"""
    files = await FileService.list_files(str(user.id), session_id)
    return [
        FileListResponse(
            id=f.id,
            filename=f.filename,
            original_name=f.original_name,
            content_type=f.content_type,
            size=f.size,
            session_id=f.session_id,
            created_at=f.created_at,
        )
        for f in files
    ]


@router.get("/{file_id}/download", summary="下载文件")
async def download_file(
    file_id: str,
    user: User = Depends(get_current_user),
):
    """下载用户上传的文件"""
    user_file = await FileService.get_file(str(user.id), file_id)
    if not user_file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
    
    import os
    if not os.path.exists(user_file.local_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件已被删除")
    
    def file_iterator():
        with open(user_file.local_path, "rb") as f:
            while chunk := f.read(8192):
                yield chunk
    
    return StreamingResponse(
        file_iterator(),
        media_type=user_file.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{user_file.original_name}"',
        },
    )


# ==================== 用户上传文件操作 ====================

@router.get("/uploads/{session_id}/list", summary="列出用户上传的文件")
async def list_uploaded_files(
    session_id: str,
    user: User = Depends(get_current_user),
):
    """列出用户上传的文件（对话时会自动同步到沙箱）"""
    sandbox_file_service = SandboxFileService(None)
    files = await sandbox_file_service.list_uploaded_files(session_id)
    return {"session_id": session_id, "files": files}


@router.get("/uploads/{session_id}/download", summary="下载用户上传的文件")
async def download_uploaded_file(
    session_id: str,
    filename: str = Query(..., description="文件名"),
    user: User = Depends(get_current_user),
):
    """下载用户上传的文件"""
    sandbox_file_service = SandboxFileService(None)
    content = await sandbox_file_service.download_uploaded_file(session_id, filename)
    
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
    
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get("/sandbox/{session_id}/binding", response_model=SandboxBindingResponse, summary="获取沙箱绑定信息")
async def get_sandbox_binding(
    session_id: str,
    user: User = Depends(get_current_user),
):
    """获取会话关联的沙箱 ID、工作目录、已同步文件等信息"""
    binding = await SandboxBindingRepository.get_by_session(session_id)
    if not binding:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到沙箱绑定")
    
    if binding.user_id != str(user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问")
    
    return SandboxBindingResponse(
        id=binding.id,
        session_id=binding.session_id,
        sandbox_id=binding.sandbox_id,
        workspace_path=binding.workspace_path,
        is_active=binding.is_active,
        synced_file_ids=[str(fid) for fid in binding.synced_file_ids],
        created_at=binding.created_at,
        updated_at=binding.updated_at,
    )


# ==================== 沙箱工作目录文件操作 ====================

def _scan_directory(path: str, relative_path: str = "", show_hidden: bool = False) -> List[SandboxFileItem]:
    """递归扫描目录，返回文件树"""
    items = []
    try:
        for entry in os.scandir(path):
            # 过滤以点开头的隐藏文件/文件夹
            if not show_hidden and entry.name.startswith('.'):
                continue
                
            item_path = f"{relative_path}/{entry.name}" if relative_path else entry.name
            stat = entry.stat()
            
            if entry.is_file():
                items.append(SandboxFileItem(
                    name=entry.name,
                    path=item_path,
                    type="file",
                    size=stat.st_size,
                    modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                ))
            elif entry.is_dir():
                # 递归扫描子目录
                children = _scan_directory(entry.path, item_path, show_hidden)
                items.append(SandboxFileItem(
                    name=entry.name,
                    path=item_path,
                    type="directory",
                    modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    children=children,
                ))
    except PermissionError:
        pass
    
    # 目录在前，文件在后，按名称排序
    items.sort(key=lambda x: (x.type == "file", x.name.lower()))
    return items


@router.get("/sandbox/{session_id}/workspace", response_model=List[SandboxFileItem], summary="获取沙箱工作目录文件列表")
async def list_sandbox_workspace(
    session_id: str,
    path: str = Query("", description="相对路径，空为根目录"),
    user: User = Depends(get_current_user),
):
    """
    获取沙箱工作目录（/workspace）的文件列表。
    
    返回完整的文件树结构，包含子目录。
    """
    binding = await SandboxBindingRepository.get_by_session(session_id)
    if not binding:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到沙箱绑定")
    
    if binding.user_id != str(user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问")
    
    mount_dir = binding.mount_dir
    if not mount_dir or not os.path.exists(mount_dir):
        return []
    
    # 构建目标路径
    target_path = os.path.join(mount_dir, path) if path else mount_dir
    
    # 安全检查：防止路径遍历
    target_path = os.path.realpath(target_path)
    mount_dir_real = os.path.realpath(mount_dir)
    if not target_path.startswith(mount_dir_real):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效路径")
    
    if not os.path.exists(target_path):
        return []
    
    if os.path.isfile(target_path):
        # 如果是文件，返回单个文件信息
        stat = os.stat(target_path)
        return [SandboxFileItem(
            name=os.path.basename(target_path),
            path=path,
            type="file",
            size=stat.st_size,
            modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
        )]
    
    return _scan_directory(target_path, path)


@router.get("/sandbox/{session_id}/workspace/download", summary="下载沙箱工作目录文件")
async def download_sandbox_file(
    session_id: str,
    path: str = Query(..., description="文件相对路径"),
    user: User = Depends(get_current_user),
):
    """下载沙箱工作目录中的文件"""
    binding = await SandboxBindingRepository.get_by_session(session_id)
    if not binding:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到沙箱绑定")
    
    if binding.user_id != str(user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问")
    
    mount_dir = binding.mount_dir
    if not mount_dir:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="沙箱未挂载")
    
    # 构建目标路径
    target_path = os.path.join(mount_dir, path)
    
    # 安全检查：防止路径遍历
    target_path = os.path.realpath(target_path)
    mount_dir_real = os.path.realpath(mount_dir)
    if not target_path.startswith(mount_dir_real):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效路径")
    
    if not os.path.exists(target_path) or not os.path.isfile(target_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
    
    filename = os.path.basename(target_path)
    
    def file_iterator():
        with open(target_path, "rb") as f:
            while chunk := f.read(8192):
                yield chunk
    
    # RFC 5987: 使用 UTF-8 编码文件名，支持中文等非 ASCII 字符
    from urllib.parse import quote
    filename_encoded = quote(filename, safe='')
    content_disposition = f"attachment; filename*=UTF-8''{filename_encoded}"
    
    return StreamingResponse(
        file_iterator(),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": content_disposition,
        },
    )


@router.get("/sandbox/{session_id}/workspace/content", summary="获取文件内容")
async def get_sandbox_file_content(
    session_id: str,
    path: str = Query(..., description="文件相对路径"),
    user: User = Depends(get_current_user),
):
    """获取沙箱文件内容（用于预览）"""
    binding = await SandboxBindingRepository.get_by_session(session_id)
    if not binding:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到沙箱绑定")
    
    if binding.user_id != str(user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问")
    
    mount_dir = binding.mount_dir
    if not mount_dir:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="沙箱未挂载")
    
    target_path = os.path.join(mount_dir, path)
    target_path = os.path.realpath(target_path)
    mount_dir_real = os.path.realpath(mount_dir)
    
    if not target_path.startswith(mount_dir_real):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效路径")
    
    if not os.path.exists(target_path) or not os.path.isfile(target_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
    
    # 获取文件大小，限制预览大小（最大1MB）
    file_size = os.path.getsize(target_path)
    max_size = 1 * 1024 * 1024
    
    # 获取文件扩展名
    ext = os.path.splitext(path)[1].lower()
    
    # 图片文件类型 - 返回特殊标记以便前端显示
    image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.webp', '.svg'}
    if ext in image_extensions:
        return {"content": None, "binary": True, "image": True, "size": file_size, "path": path}
    
    # HTML 文件 - 返回特殊标记以便前端渲染
    if ext in {'.html', '.htm'}:
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                content = f.read()
            return {"content": content, "binary": False, "html": True, "size": file_size, "path": path}
        except UnicodeDecodeError:
            return {"content": None, "binary": True, "size": file_size, "path": path}
    
    # 其他二进制文件类型
    binary_extensions = {'.pdf', '.zip', '.tar', '.gz', '.rar', '.7z',
                         '.exe', '.dll', '.so', '.dylib', '.bin', '.dat',
                         '.mp3', '.mp4', '.avi', '.mov', '.wav', '.flac'}
    
    if ext in binary_extensions:
        return {"content": None, "binary": True, "size": file_size, "path": path}
    
    try:
        with open(target_path, "r", encoding="utf-8") as f:
            if file_size > max_size:
                content = f.read(max_size) + "\n\n... (文件过大，已截断)"
            else:
                content = f.read()
        return {"content": content, "binary": False, "size": file_size, "path": path}
    except UnicodeDecodeError:
        return {"content": None, "binary": True, "size": file_size, "path": path}


@router.get("/sandbox/{session_id}/workspace/raw", summary="获取文件原始内容")
async def get_sandbox_file_raw(
    session_id: str,
    path: str = Query(..., description="文件相对路径"),
):
    """获取沙箱文件原始内容（用于图片/HTML预览，无需认证，session_id本身作为访问控制）"""
    binding = await SandboxBindingRepository.get_by_session(session_id)
    if not binding:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到沙箱绑定")
    
    mount_dir = binding.mount_dir
    if not mount_dir:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="沙箱未挂载")
    
    target_path = os.path.join(mount_dir, path)
    target_path = os.path.realpath(target_path)
    mount_dir_real = os.path.realpath(mount_dir)
    
    if not target_path.startswith(mount_dir_real):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效路径")
    
    if not os.path.exists(target_path) or not os.path.isfile(target_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
    
    # 根据扩展名确定 MIME 类型
    ext = os.path.splitext(path)[1].lower()
    mime_types = {
        '.html': 'text/html', '.htm': 'text/html',
        '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.gif': 'image/gif', '.bmp': 'image/bmp', '.ico': 'image/x-icon',
        '.webp': 'image/webp', '.svg': 'image/svg+xml',
    }
    media_type = mime_types.get(ext, 'application/octet-stream')
    
    # HTML 文件特殊处理：将相对路径图片转换为 API 路径
    if ext in ('.html', '.htm'):
        import re
        with open(target_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        
        # 获取文件所在目录（相对路径）
        file_dir = path.rsplit('/', 1)[0] + '/' if '/' in path else ''
        
        # 替换相对路径图片为 API 路径
        def replace_img_src(match):
            prefix, src, suffix = match.groups()
            # 构建完整的 API 路径
            full_path = file_dir + src
            api_url = f"/api/files/sandbox/{session_id}/workspace/raw?path={full_path}"
            return prefix + api_url + suffix
        
        html_content = re.sub(
            r'(<img[^>]*\ssrc=["\'])(?!https?://|data:|/api/)([^"\']+)(["\'][^>]*>)',
            replace_img_src,
            html_content,
            flags=re.IGNORECASE
        )
        
        return Response(content=html_content, media_type="text/html; charset=utf-8")
    
    def file_iterator():
        with open(target_path, "rb") as f:
            while chunk := f.read(8192):
                yield chunk
    
    return StreamingResponse(
        file_iterator(),
        media_type=media_type,
    )


class SaveFileRequest(BaseModel):
    """保存文件请求"""
    content: str


@router.put("/sandbox/{session_id}/workspace/content", summary="保存文件内容")
async def save_sandbox_file_content(
    session_id: str,
    path: str = Query(..., description="文件相对路径"),
    data: SaveFileRequest = None,
    user: User = Depends(get_current_user),
):
    """
    保存沙箱文件内容（需要验证用户身份）
    
    只有文件所有者可以编辑，分享链接的访问者无权编辑。
    """
    binding = await SandboxBindingRepository.get_by_session(session_id)
    if not binding:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到沙箱绑定")
    
    # 验证用户身份：只有所有者可以编辑
    if binding.user_id != str(user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权编辑此文件")
    
    mount_dir = binding.mount_dir
    if not mount_dir:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="沙箱未挂载")
    
    target_path = os.path.join(mount_dir, path)
    target_path = os.path.realpath(target_path)
    mount_dir_real = os.path.realpath(mount_dir)
    
    # 安全检查：防止路径遍历
    if not target_path.startswith(mount_dir_real):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效路径")
    
    if not os.path.exists(target_path) or not os.path.isfile(target_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
    
    # 只允许编辑 HTML 文件
    ext = os.path.splitext(path)[1].lower()
    if ext not in {'.html', '.htm'}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持编辑 HTML 文件")
    
    try:
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(data.content)
        return {"success": True, "message": "文件已保存", "path": path}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"保存失败: {str(e)}")


@router.get("/sandbox/{session_id}/workspace/zip", summary="下载整个工作目录为ZIP")
async def download_workspace_zip(
    session_id: str,
    user: User = Depends(get_current_user),
):
    """将整个沙箱工作目录打包为ZIP下载"""
    import zipfile
    import tempfile
    
    binding = await SandboxBindingRepository.get_by_session(session_id)
    if not binding:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到沙箱绑定")
    
    if binding.user_id != str(user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问")
    
    mount_dir = binding.mount_dir
    if not mount_dir or not os.path.exists(mount_dir):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="沙箱未挂载")
    
    # 创建临时ZIP文件
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    try:
        with zipfile.ZipFile(temp_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(mount_dir):
                # 过滤隐藏目录
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                for file in files:
                    # 过滤隐藏文件
                    if file.startswith('.'):
                        continue
                    file_path = os.path.join(root, file)
                    arc_name = os.path.relpath(file_path, mount_dir)
                    zf.write(file_path, arc_name)
        
        temp_file.close()
        
        def file_iterator():
            with open(temp_file.name, "rb") as f:
                while chunk := f.read(8192):
                    yield chunk
            os.unlink(temp_file.name)
        
        return StreamingResponse(
            file_iterator(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="workspace_{session_id[:8]}.zip"',
            },
        )
    except Exception as e:
        os.unlink(temp_file.name)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
